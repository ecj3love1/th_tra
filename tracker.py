import requests
import re
import os
import hashlib
from supabase import create_client, Client

# ==========================================
# 1. API 키 및 설정
# ==========================================
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

PLAYLIST_ID = "UUX6OQ3DkcsbYNE6H8uQQuVA"
TARGET_DATE = "2018-02-23T00:00:00Z"

# 수파베이스 연결
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. 영상 길이 변환 함수
# ==========================================
def get_total_seconds(duration_str):
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match: return 0
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0
    return hours * 3600 + minutes * 60 + seconds

# ==========================================
# 3. 사진 지문(Hash) 추출 함수 (핵심 추가 기능)
# ==========================================
def get_image_data(url):
    try:
        res = requests.get(url)
        if res.status_code == 200:
            image_content = res.content
            # 사진 데이터를 바탕으로 고유한 지문(SHA-256) 생성
            image_hash = hashlib.sha256(image_content).hexdigest()
            return image_hash, image_content
    except Exception as e:
        print(f"이미지 다운로드 실패: {e}")
    return None, None

# ==========================================
# 4. 메인 수집 및 DB 저장 함수
# ==========================================
def fetch_and_save_videos():
    video_dict = {}
    video_ids = []
    next_page_token = ""
    
    print("🚀 [1단계] 유튜브 영상 데이터를 수집합니다...")

    while True:
        page_query = f"&pageToken={next_page_token}" if next_page_token else ""
        playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId={PLAYLIST_ID}&key={YOUTUBE_API_KEY}{page_query}"
        
        res = requests.get(playlist_url)
        if res.status_code != 200:
            print("🚨 유튜브 API 에러!")
            return
            
        data = res.json()
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            published_at = snippet.get("publishedAt", "")
            
            if published_at < TARGET_DATE:
                continue
                
            video_id = snippet.get("resourceId", {}).get("videoId")
            thumbnails = snippet.get("thumbnails", {})
            thumbnail_url = thumbnails.get("maxres", {}).get("url") or thumbnails.get("high", {}).get("url") or "썸네일 없음"
            
            if thumbnail_url != "썸네일 없음":
                video_dict[video_id] = {
                    "title": snippet.get("title"),
                    "thumbnail": thumbnail_url,
                    "published_at": published_at
                }
                video_ids.append(video_id)
            
        next_page_token = data.get("nextPageToken")
        if not next_page_token: break

    print(f"✅ {len(video_ids)}개의 영상 발견!")
    print("⏳ [2단계] 영상을 필터링하고 사진 지문을 검사합니다...")

    videos_to_insert = []
    thumbnails_to_check = []
    
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        ids_string = ",".join(chunk)
        
        video_url = f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails&id={ids_string}&key={YOUTUBE_API_KEY}"
        video_items = requests.get(video_url).json().get("items", [])
        
        for v_item in video_items:
            v_id = v_item.get("id")
            duration_str = v_item.get("contentDetails", {}).get("duration", "")
            
            if get_total_seconds(duration_str) > 180:
                info = video_dict[v_id]
                videos_to_insert.append({
                    "id": v_id,
                    "title": info["title"],
                    "published_at": info["published_at"]
                })
                thumbnails_to_check.append({
                    "video_id": v_id,
                    "thumbnail_url": info["thumbnail"]
                })

    try:
        # 1. videos 테이블 업데이트
        supabase.table("videos").upsert(videos_to_insert).execute()
        
        # 2. 썸네일 검사 및 내 창고 영구 보존 로직
        changed_count = 0
        for t in thumbnails_to_check:
            v_id = t["video_id"]
            yt_thumb_url = t["thumbnail_url"]
            
            # 유튜브에서 사진을 몰래 다운받아 지문 채취
            img_hash, img_content = get_image_data(yt_thumb_url)
            if not img_hash:
                continue
                
            # DB에서 이 영상의 가장 최근 지문 가져오기
            res = supabase.table("thumbnail_history").select("image_hash").eq("video_id", v_id).order("checked_at", desc=True).limit(1).execute()
            latest_hash = res.data[0]["image_hash"] if res.data and res.data[0].get("image_hash") else None
            
            # ⭐️ 지문이 다르면 (즉, 유튜버가 사진을 바꿨거나 처음 저장하는 경우면)
            if latest_hash != img_hash:
                # 창고에 저장될 파일 이름: "영상아이디_지문.jpg"
                file_name = f"{v_id}_{img_hash}.jpg"
                
                # 1) 내 창고(Storage)에 진짜 사진 파일 업로드
                try:
                    response = supabase.storage.from_("thumbnails").upload(
                        path=file_name,
                        file=img_content,
                        file_options={"content-type": "image/jpeg"}
                    )
                    print(f"✅ 업로드 성공: {file_name}")
                except Exception as e:
                    print(f"❌ 업로드 실패 상세: {e}") # 에러 내용을 직접 출력!
                
                # 2) 내 창고의 영구 접속 주소 가져오기
                storage_url = supabase.storage.from_("thumbnails").get_public_url(file_name)
                
                # 3) DB에 기록 (유튜브 주소가 아닌 내 창고 주소와 지문을 저장)
                supabase.table("thumbnail_history").insert({
                    "video_id": v_id,
                    "thumbnail_url": storage_url,
                    "image_hash": img_hash
                }).execute()
                
                changed_count += 1
                print(f"🔄 썸네일 영구 저장 됨: {v_id}")

        print(f"🎉 스케줄러 실행 완료! 새로운 썸네일 {changed_count}개 내 창고에 영구 보존됨.")
        
    except Exception as e:
        print(f"🚨 에러 발생: {e}")

if __name__ == "__main__":
    fetch_and_save_videos()
