import requests
import re
import os
from supabase import create_client, Client

# ==========================================
# 1. API 키 및 설정 (안전하게 숨기기)
# ==========================================
# GitHub Secrets에 저장해둔 값을 불러오도록 수정합니다.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

PLAYLIST_ID = "UUX6OQ3DkcsbYNE6H8uQQuVA"
TARGET_DATE = "2018-02-23T00:00:00Z"

# 수파베이스 클라이언트 연결
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ... (2. 영상 길이 변환 함수는 기존과 동일하게 유지) ...
def get_total_seconds(duration_str):
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match: return 0
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0
    return hours * 3600 + minutes * 60 + seconds

# ... (3. 메인 수집 함수 STEP 1, STEP 2 부분도 기존과 동일하게 유지) ...

    # ==========================================
    # [STEP 3] 수파베이스(DB)에 데이터 쏘기 (수정된 부분)
    # ==========================================
    try:
        # 1. videos 테이블에 정보 저장 (upsert로 영상 정보 덮어쓰기)
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