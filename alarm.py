#!/usr/bin/env python3
"""
alarm.py — 간단한 알람 시계

지정된 시간까지 대기한 후 macOS 시스템 사운드를 반복 재생합니다.
기본값: 내일 아침 7:00, "Funk.aiff" 사운드, 10회 반복.

사용법:
    python3 alarm.py                        # 내일 아침 7:00
    python3 alarm.py --hour 8 --minute 30   # 내일 8:30
    python3 alarm.py --sound Ping.aiff      # 사운드 변경
    python3 alarm.py --repeat 20            # 반복 횟수
    python3 alarm.py --hour 14 --minute 0 --today  # 오늘 오후 2:00 (테스트용)
"""

import argparse
import datetime
import os
import subprocess
import sys
import time


SOUND_DIR = "/System/Library/Sounds"
DEFAULT_SOUND = "Funk.aiff"
DEFAULT_HOUR = 7
DEFAULT_MINUTE = 0
DEFAULT_REPEAT = 10
REPEAT_INTERVAL = 2  # seconds between repeats


def parse_args():
    parser = argparse.ArgumentParser(description="간단한 macOS 알람 시계")
    parser.add_argument("--hour", type=int, default=DEFAULT_HOUR,
                        help=f"알람 시 (24시간제, 기본값: {DEFAULT_HOUR})")
    parser.add_argument("--minute", type=int, default=DEFAULT_MINUTE,
                        help=f"알람 분 (기본값: {DEFAULT_MINUTE})")
    parser.add_argument("--sound", type=str, default=DEFAULT_SOUND,
                        help=f"재생할 사운드 파일 이름 (기본값: {DEFAULT_SOUND})")
    parser.add_argument("--repeat", type=int, default=DEFAULT_REPEAT,
                        help=f"반복 재생 횟수 (기본값: {DEFAULT_REPEAT})")
    parser.add_argument("--today", action="store_true",
                        help="오늘 날짜 기준 (지난 시간이면 하루 더함)")
    parser.add_argument("--interval", type=float, default=REPEAT_INTERVAL,
                        help=f"재생 간격 초 (기본값: {REPEAT_INTERVAL})")
    parser.add_argument("--say", type=str, default=None,
                        help="알람 시작 시 음성으로 읽을 메시지 (macOS say)")
    return parser.parse_args()


def get_target_time(hour: int, minute: int, today: bool) -> datetime.datetime:
    """목표 알람 시각을 계산한다."""
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if today:
        # 오늘이지만 이미 지났다면 다음 날
        if target <= now:
            target += datetime.timedelta(days=1)
    else:
        # 기본: 내일
        target += datetime.timedelta(days=1)

    return target


def main():
    args = parse_args()

    # 사운드 경로 확인
    sound_path = f"{SOUND_DIR}/{args.sound}"
    if not os.path.isfile(sound_path):
        print(f"[오류] 사운드 파일을 찾을 수 없습니다: {sound_path}")
        print(f"       사용 가능한 사운드: {', '.join(sorted(os.listdir(SOUND_DIR)))}")
        sys.exit(1)

    target = get_target_time(args.hour, args.minute, args.today)
    now = datetime.datetime.now()
    wait_seconds = (target - now).total_seconds()

    print(f"⏰ 알람 설정됨")
    print(f"   시각: {target.strftime('%Y-%m-%d %H:%M')} ({args.hour:02d}:{args.minute:02d})")
    print(f"   사운드: {args.sound}")
    print(f"   반복: {args.repeat}회")
    print(f"   대기 시간: {wait_seconds:.0f}초 ({wait_seconds/3600:.1f}시간)")

    if wait_seconds <= 0:
        print("[오류] 목표 시각이 이미 지났습니다.")
        sys.exit(1)

    # ── 대기 ──
    try:
        print(f"\n💤 대기 중... (Ctrl+C로 취소)")
        while wait_seconds > 0:
            mins, secs = divmod(int(wait_seconds), 60)
            hours, mins = divmod(mins, 60)
            print(f"   남은 시간: {hours}시간 {mins}분 {secs}초", end="\r")
            sleep_chunk = min(wait_seconds, 60)  # 60초 단위로 갱신
            time.sleep(sleep_chunk)
            now = datetime.datetime.now()
            wait_seconds = (target - now).total_seconds()
        print("\n")
    except KeyboardInterrupt:
        print("\n⚠️  알람이 취소되었습니다.")
        sys.exit(0)

    # ── 알람 울림 ──
    print("🔔 알람! 일어나세요!\n")

    if args.say:
        subprocess.run(["say", args.say])

    for i in range(args.repeat):
        print(f"   ▶ 재생 {i+1}/{args.repeat}: {args.sound}")
        try:
            subprocess.run(["afplay", sound_path], check=True, timeout=30)
        except subprocess.TimeoutExpired:
            pass
        except KeyboardInterrupt:
            print("\n🛑 알람 중단.")
            sys.exit(0)

        if i < args.repeat - 1:
            time.sleep(args.interval)

    print("\n✅ 알람 종료. 좋은 하루 되세요!")


if __name__ == "__main__":
    main()
