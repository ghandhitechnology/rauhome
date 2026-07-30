"""What the activity plane says, in the reader's language.

Every line the inspector shows about a turn — the name of the tool that is
running, whether it finished, the sentence summarizing the approach — is
composed here rather than in the hub, so a Korean session sees Korean activity
instead of a Korean interface wrapped around an English trace.

Two rules keep this honest:

  · These are *labels for observable work*, not reasoning. Translating them
    changes the language, never the claim.
  · Tool names, file paths and provider errors pass through untouched. They
    are identifiers, and a translated identifier is a wrong one.
"""
from __future__ import annotations

from typing import Dict

from rau.language import get_locale

#: The verb for each tool, as the timeline names it while it runs.
_TOOL_LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "read_file": "Reading a file",
        "write_file": "Writing a file",
        "edit_file": "Editing a file",
        "run_shell": "Running a command",
        "browse_web": "Browsing the web",
        "start_hard_task": "Starting deep work",
        "cancel_hard_task": "Stopping deep work",
        "redirect_hard_task": "Redirecting deep work",
        "use_skill": "Loading a skill",
        "list_skills": "Checking available skills",
        "set_goal": "Setting the goal",
        "clear_goal": "Clearing the goal",
        "goal_note": "Recording goal progress",
        "memory_write": "Saving a memory",
        "memory_read": "Checking memory",
        "body_choreography": "Planning movement",
        "move_object": "Moving an object",
        "start_kittens": "Dealing a game",
        "end_kittens": "Clearing the table",
        "start_chess": "Setting the board up",
        "chess_move": "Making a decision at the board",
        "end_chess": "Putting the board away",
        "show_panel": "Making something to look at",
        "list_panels": "Looking at the wall",
        "update_panel": "Changing a panel",
        "close_panel": "Taking a panel down",
        "present_panel": "Putting a panel up on screen",
        "commission_panel": "Sending someone to build a panel",
        # deep work only
        "memory_write_note": "Saving a note",
        "spawn_subagent": "Delegating read-only work",
        "computer_observe": "Observing the screen",
        "computer_inspect_ui": "Inspecting the interface",
        "computer_act": "Using the computer",
        "computer_assert": "Checking the interface",
        "create_schedule": "Creating a schedule",
        "update_schedule": "Updating a schedule",
        "list_schedules": "Reading schedules",
        "finish": "Finishing the step",
    },
    # Nominalized (명사형) rather than progressive: this is both how a Korean
    # interface labels a running step and the only form that composes into the
    # spoken check-in and the trace summary without re-inflecting per sentence.
    "ko": {
        "read_file": "파일 읽기",
        "write_file": "파일 쓰기",
        "edit_file": "파일 수정",
        "run_shell": "명령 실행",
        "browse_web": "웹 열람",
        "start_hard_task": "딥 워크 시작",
        "cancel_hard_task": "딥 워크 중단",
        "redirect_hard_task": "딥 워크 방향 전환",
        "use_skill": "스킬 불러오기",
        "list_skills": "스킬 목록 확인",
        "set_goal": "목표 설정",
        "clear_goal": "목표 지우기",
        "goal_note": "목표 진행 기록",
        "memory_write": "기억 저장",
        "memory_read": "기억 확인",
        "body_choreography": "움직임 구성",
        "move_object": "물건 옮기기",
        "start_kittens": "카드 돌리기",
        "end_kittens": "테이블 정리",
        "start_chess": "체스판 놓기",
        "chess_move": "판 앞에서 수 고르기",
        "end_chess": "체스판 치우기",
        "show_panel": "볼 것 만들기",
        "list_panels": "벽 살펴보기",
        "update_panel": "패널 수정",
        "close_panel": "패널 내리기",
        "present_panel": "패널 띄우기",
        "commission_panel": "패널 제작 의뢰",
        # deep work only
        "memory_write_note": "메모 저장",
        "spawn_subagent": "읽기 전용 작업 위임",
        "computer_observe": "화면 관찰",
        "computer_inspect_ui": "화면 요소 확인",
        "computer_act": "컴퓨터 조작",
        "computer_assert": "화면 상태 점검",
        "create_schedule": "일정 생성",
        "update_schedule": "일정 수정",
        "list_schedules": "일정 조회",
        "finish": "단계 마무리",
    },
}

#: Fixed lines the span lifecycle emits.
_PHRASES: Dict[str, Dict[str, str]] = {
    "en": {
        "responding": "Responding",
        "reasoning": "Reasoning",
        "approach": "Approach summary",
        "composing": "Composing the response",
        "reasoning_done": "Reasoning complete",
        "response_ready": "Response ready",
        "reasoning_interrupted": "Reasoning interrupted",
        "response_interrupted": "Response interrupted",
        "reasoning_failed": "Reasoning failed",
        "response_failed": "Response failed",
        "finished": "Finished",
        "tool_failed": "Tool failed",
        "failed_suffix": "{label} failed",
        "using": "Using {name}",
        # deep work
        "planning": "Planning the work",
        "planning_summary": "Building a validated execution plan",
        "working": "Working on the task",
        "queued": "Queued",
        "plan_made": "Created a {count}-step plan",
        "paused": "Paused by user",
        "resuming": "Resuming",
        "plan_revised": "Plan revised",
        "steering_added": "Added a bounded steering step",
        "revision_ready": "Plan revision {revision} ready",
        "awaiting_approval": "Waiting for approval",
        "approved": "Approved",
        "denied": "Denied or expired",
        "attempt": "Attempt {attempt}",
        "attempt_queued": "Attempt {attempt} queued",
        "checking": "Checking the result",
        "checking_summary": "Evaluating the step evidence",
        "verified": "Verified with {count} evidence item(s)",
        "contract_accepted": "Completion contract accepted",
        "retrying": "Trying a different strategy",
        "retry_after": "Retrying after: {message}",
        "repair_step": "Adding a repair step",
        "step_reasoning": "Reasoning about the step",
        "validating": "Validating arguments",
        "reading_named": "Reading {name}",
    },
    "ko": {
        "responding": "답하는 중",
        "reasoning": "추론",
        "approach": "작업 요약",
        "composing": "답을 쓰는 중",
        "reasoning_done": "추론 완료",
        "response_ready": "답 준비됨",
        "reasoning_interrupted": "추론이 중단됨",
        "response_interrupted": "답이 중단됨",
        "reasoning_failed": "추론 실패",
        "response_failed": "답하기 실패",
        "finished": "완료",
        "tool_failed": "도구 실패",
        "failed_suffix": "{label} 실패",
        "using": "{name} 사용",
        # deep work
        "planning": "작업 계획 세우는 중",
        "planning_summary": "검증까지 포함한 실행 계획을 짜는 중",
        "working": "작업 진행 중",
        "queued": "대기 중",
        "plan_made": "{count}단계 계획을 세웠습니다",
        "paused": "사용자가 멈춤",
        "resuming": "다시 시작하는 중",
        "plan_revised": "계획 수정됨",
        "steering_added": "범위를 정한 지시 단계를 추가했습니다",
        "revision_ready": "{revision}차 수정 계획 준비됨",
        "awaiting_approval": "승인 대기 중",
        "approved": "승인됨",
        "denied": "거절되었거나 만료됨",
        "attempt": "{attempt}번째 시도",
        "attempt_queued": "{attempt}번째 시도 대기 중",
        "checking": "결과 확인 중",
        "checking_summary": "단계의 근거를 살펴보는 중",
        "verified": "근거 {count}건으로 확인했습니다",
        "contract_accepted": "완료 조건을 충족했습니다",
        "retrying": "다른 방법으로 시도",
        "retry_after": "이 문제 뒤에 다시 시도: {message}",
        "repair_step": "복구 단계 추가",
        "step_reasoning": "이 단계에 대한 추론",
        "validating": "인자 검증 중",
        "reading_named": "{name} 읽기",
    },
}


def _lang() -> str:
    return "ko" if get_locale() == "ko" else "en"


def phrase(key: str, **values: object) -> str:
    """One fixed activity line, formatted."""
    text = _PHRASES[_lang()].get(key) or _PHRASES["en"].get(key, key)
    return text.format(**values) if values else text


def known_tool_label(name: str) -> str:
    """The translated label for a tool, or "" if this tool has no entry."""
    return _TOOL_LABELS[_lang()].get(name) or _TOOL_LABELS["en"].get(name) or ""


def tool_label(name: str) -> str:
    """What the timeline calls a tool. Unknown tools keep their own name."""
    return known_tool_label(name) or phrase("using", name=name.replace("_", " "))


def trace_summary(
    *,
    tool_count: int,
    actions: str,
    failures: int,
    final: bool,
    interrupted: bool,
    provider_reasoning: bool,
) -> str:
    """The one-paragraph account of a turn's observable work.

    Assembled from clauses rather than one format string: Korean puts the verb
    last, so "completed so far: A, B. 2 reported a failure." cannot be built by
    substituting into the English sentence's slots.
    """
    if _lang() == "ko":
        if not tool_count:
            if interrupted:
                base = "도구를 하나도 마치기 전에 차례가 끊겼습니다."
            elif final:
                base = "도구 없이 바로 답했습니다."
            else:
                base = "바로 답할 내용을 정리하는 중입니다."
        else:
            state = "완료" if final else "진행"
            base = f"도구 호출 {tool_count}건 {state}: {actions}."
            if failures:
                base += f" 그중 {failures}건은 실패했습니다."
            if interrupted:
                base += " 그 뒤 앞선 차례가 중단됐습니다."
            elif final:
                base += " 그 결과를 모아 답을 썼습니다."
        if provider_reasoning:
            base += " 이 요약은 겉으로 드러난 작업 기준이며, 제공자가 추론 기록도 함께 남겼습니다."
        else:
            base += " 이 요약은 겉으로 드러난 작업 기준이며, 제공자는 추론 기록을 남기지 않았습니다."
        return base

    if not tool_count:
        if interrupted:
            base = "The turn was interrupted before any tool call completed."
        elif final:
            base = "Answered directly; no tool calls were needed."
        else:
            base = "Working out a direct response."
    else:
        state = "completed" if final else "completed so far"
        base = f"{tool_count} tool calls {state}: {actions}."
        if failures:
            base += f" {failures} reported a failure."
        if interrupted:
            base += " The foreground turn was then interrupted."
        elif final:
            base += " Used the results to compose the response."
    if provider_reasoning:
        base += (
            " Action summary uses observable work; the provider also "
            "exposed a reasoning trace."
        )
    else:
        base += (
            " Summary is based on observable actions; the provider "
            "exposed no reasoning trace."
        )
    return base
