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

# ⭐️ 채널별로 플레이리스트 ID와 타겟 날짜를 각각 지정!
TRACK_CHANNELS = {
    "MrBeast": {
        "playlist_id": "UUX6OQ3DkcsbYNE6H8uQQuVA",
        "target_date": "2018-02-23T00:00:00Z"
    },
    "Ryan Trahan": {
        "playlist_id": "UUnmGIkw-KdI0W5siakKPKog", 
        "target_date": "2021-01-01T00:00:00Z"
    },
    "Mark Rober": {
        "playlist_id": "UUY1kMZp36IQSyNx_9h4mpCg", 
        "target_date": "2017-07-12T00:00:00Z"
    },
    "Gonzok": {
        "playlist_id": "UUpDqD6Py6uGz-w6nYJqTJtQ", 
        "target_date": "2022-07-09T00:00:00Z"
    },
    "Mack": {
        "playlist_id": "UUcEYnFxkf9WT_e4rMnRPI1g", 
        "target_date": "2026-03-06T00:00:00Z"
    }
}

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
# 3. 사진 지문(Hash) 추출 함수
# ==========================================
def get_image_data(url):
    try:
        res = requests.get(url)
        if res.status_code == 200:
            image_content = res.content
            image_hash = hashlib.sha256(image_content).hexdigest()
            return image_hash, image_content
    except Exception as e:
        print(f"이미지 다운로드 실패: {e}")
    return None, None

# ==========================================
# 4. (추가됨) 채널 정보(프로필 사진) 자동 등록 함수
# ==========================================
def auto_register_channel(channel_name, playlist_id):
    # 재생목록 ID(UU...)를 채널 ID(UC...)로 변환
    channel_id = "UC" + playlist_id[2:]
    
    # 유튜브 채널 API 호출해서 프사 가져오기
    url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet&id={channel_id}&key={YOUTUBE_API_KEY}"
    
    try:
        res = requests.get(url)
        if res.status_code == 200:
            data = res.json()
            if data.get("items"):
                profile_url = data["items"][0]["snippet"]["thumbnails"]["high"]["url"]
                
                # 수파베이스에 이미 해당 채널이 있는지 확인
                existing = supabase.table("channels").select("id").eq("name", channel_name).execute()
                
                if not existing.data:
                    # 없으면 새로 자동 등록
                    supabase.table("channels").insert({
                        "name": channel_name,
                        "profile_url": profile_url
                    }).execute()
                    print(f"🌟 [{channel_name}] 채널 정보(프사) 자동 등록 완료!")
                else:
                    # 이미 있으면 프사 주소 최신화
                    supabase.table("channels").update({
                        "profile_url": profile_url
                    }).eq("name", channel_name).execute()
                    
    except Exception as e:
        print(f"🚨 [{channel_name}] 채널 자동 등록 실패: {e}")

# ==========================================
# 5. 단일 채널 수집 및 DB 저장 함수
# ==========================================
def process_channel_videos(channel_name, playlist_id, target_date):
    video_dict = {}
    video_ids = []
    next_page_token = ""
    
    print(f"\n🚀 [{channel_name}] 유튜브 영상 데이터를 수집합니다... (타겟: {target_date} 이후)")

    while True:
        page_query = f"&pageToken={next_page_token}" if next_page_token else ""
        playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId={playlist_id}&key={YOUTUBE_API_KEY}{page_query}"
        
        res = requests.get(playlist_url)
        if res.status_code != 200:
            print(f"🚨 [{channel_name}] 유튜브 API 에러! 다음 채널로 넘어갑니다.")
            return
            
        data = res.json()
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            published_at = snippet.get("publishedAt", "")
            
            if published_at < target_date:
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
    if not video_ids: return

    print(f"⏳ [{channel_name}] 영상을 필터링하고 사진 지문을 검사합니다...")

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
                    "published_at": info["published_at"],
                    "channel_name": channel_name  
                })
                thumbnails_to_check.append({
                    "video_id": v_id,
                    "thumbnail_url": info["thumbnail"]
                })

    if not videos_to_insert:
        print(f"🔹 [{channel_name}] 조건(3분 초과)을 만족하는 영상이 없습니다.")
        return

    try:
        supabase.table("videos").upsert(videos_to_insert).execute()
        
        changed_count = 0
        for t in thumbnails_to_check:
            v_id = t["video_id"]
            yt_thumb_url = t["thumbnail_url"]
            
            img_hash, img_content = get_image_data(yt_thumb_url)
            if not img_hash: continue
                
            res = supabase.table("thumbnail_history").select("image_hash").eq("video_id", v_id).order("checked_at", desc=True).limit(1).execute()
            latest_hash = res.data[0]["image_hash"] if res.data and res.data[0].get("image_hash") else None
            
            if latest_hash != img_hash:
                file_name = f"{v_id}_{img_hash}.jpg"
                
                try:
                    supabase.storage.from_("thumbnails").upload(
                        path=file_name,
                        file=img_content,
                        file_options={"content-type": "image/jpeg"}
                    )
                except Exception:
                    pass 
                
                storage_url = supabase.storage.from_("thumbnails").get_public_url(file_name)
                
                supabase.table("thumbnail_history").insert({
                    "video_id": v_id,
                    "thumbnail_url": storage_url,
                    "image_hash": img_hash
                }).execute()
                
                changed_count += 1
                print(f"   🔄 썸네일 영구 저장 됨: {v_id}")

        print(f"🎉 [{channel_name}] 실행 완료! 새로운 썸네일 {changed_count}개 저장됨.")
        
    except Exception as e:
        print(f"🚨 [{channel_name}] 에러 발생: {e}")

# ==========================================
# 6. 메인 제어 함수 (모든 채널 순회)
# ==========================================
def fetch_and_save_videos():
    print("🎬 [전체 시작] 지정된 채널들의 트래킹을 시작합니다.")
    
    for name, config in TRACK_CHANNELS.items():
        # ⭐️ 영상 수집 전, 채널 프로필 사진부터 자동으로 등록/업데이트!
        auto_register_channel(name, config["playlist_id"])
        
        # 이후 해당 채널 영상 수집 진행
        process_channel_videos(name, config["playlist_id"], config["target_date"])
        
    print("\n🏁 [전체 종료] 모든 채널의 실행이 완료되었습니다.")

if __name__ == "__main__":
    fetch_and_save_videos()
