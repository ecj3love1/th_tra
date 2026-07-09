import requests
import re
import os
from supabase import create_client, Client

# ==========================================
# 1. API 키 및 설정 (안전하게 숨기기)
# ==========================================
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

PLAYLIST_ID = "UUX6OQ3DkcsbYNE6H8uQQuVA"
TARGET_DATE = "2018-02-23T00:00:00Z"

# 수파베이스 클라이언트 연결
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
# 3. 메인 수집 및 DB 저장 함수
# ==========================================
def fetch_and_save_videos():
    video_dict = {}
    video_ids = []
    next_page_token = ""
    
    print("🚀 [1단계] 유튜브 영상 데이터를 수집합니다...")

    # [STEP 1] 전체 영상 ID 및 기본 정보 수집
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
            
            video_dict[video_id] = {
                "title": snippet.get("title"),
                "thumbnail": thumbnail_url,
                "published_at": published_at
            }
            video_ids.append(video_id)
            
        next_page_token = data.get("nextPageToken")
        if not next_page_token: break

    print(f"✅ {len(video_ids)}개의 영상 발견! (2018.02.23 이후)")
    print("⏳ [2단계] 쇼츠(Shorts)를 걸러내고 DB에 저장합니다...")

    # [STEP 2] 50개씩 쪼개서 길이 확인 및 DB 저장 준비
    videos_to_insert = []
    thumbnails_to_insert = []
    
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        ids_string = ",".join(chunk)
        
        video_url = f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails&id={ids_string}&key={YOUTUBE_API_KEY}"
        video_items = requests.get(video_url).json().get("items", [])
        
        for v_item in video_items:
            v_id = v_item.get("id")
            duration_str = v_item.get("contentDetails", {}).get("duration", "")
            
            # 3분(180초) 초과 롱폼 영상만 골라내기
            if get_total_seconds(duration_str) > 180:
                info = video_dict[v_id]
                
                # videos 테이블 데이터
                videos_to_insert.append({
                    "id": v_id,
                    "title": info["title"],
                    "published_at": info["published_at"]
                })
                
                # thumbnail_history 테이블 데이터
                thumbnails_to_insert.append({
                    "video_id": v_id,
                    "thumbnail_url": info["thumbnail"]
                })

    # ==========================================
    # [STEP 3] 수파베이스(DB)에 데이터 쏘기
    # ==========================================
    try:
        # 1. videos 테이블에 정보 저장 (upsert를 써서 중복 에러 방지)
        supabase.table("videos").upsert(videos_to_insert).execute()
        
        # 2. 썸네일 변경 여부 확인 후 저장
        changed_count = 0
        for t in thumbnails_to_insert:
            v_id = t["video_id"]
            new_thumb = t["thumbnail_url"]
            
            # DB에서 이 영상의 가장 최근 썸네일 1개 가져오기
            res = supabase.table("thumbnail_history").select("thumbnail_url").eq("video_id", v_id).order("checked_at", desc=True).limit(1).execute()
            
            latest_thumb = res.data[0]["thumbnail_url"] if res.data else None
            
            # DB에 썸네일이 아예 없거나, 기존 썸네일과 다를 때만 추가!
            if latest_thumb != new_thumb:
                supabase.table("thumbnail_history").insert([t]).execute()
                changed_count += 1
                
        print(f"🎉 스케줄러 실행 완료! 새로운 썸네일 {changed_count}개 업데이트 됨.")
        
    except Exception as e:
        print(f"🚨 DB 저장 중 에러가 발생했습니다: {e}")

if __name__ == "__main__":
    fetch_and_save_videos()
