/* oxlint-disable react/only-export-components -- provider and hook are one API */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, type Locale } from './api'

export type { Locale } from './api'

export const LOCALE_KEY = 'rau.locale.v1'

const ko = {
  'nav.talk': '대화',
  'nav.face': '방',
  'nav.dashboard': '작업',
  'nav.operations': '운영',
  'nav.identity': '정체성',
  'nav.settings': '설정',
  'boot.unreachable': '허브에 연결할 수 없습니다',
  'boot.retry': '다시 시도',
  'boot.waking': '깨어나는 중',
  'language.title': '언어를 선택하세요',
  'language.lede': 'Rau의 화면과 대화 언어를 언제든 설정에서 바꿀 수 있어요.',
  'language.english': 'English',
  'language.englishNote': 'Continue in English',
  'language.korean': '한국어',
  'language.koreanNote': '한국어로 계속하기',
  'intro.skip': '건너뛰기',
  'intro.back': '뒤로',
  'intro.continue': '계속',
  'intro.begin': '설정 시작',
  'intro.eyebrow.1': '다정한 대화 친구',
  'intro.title.1': '말하고, 함께 있고, 놀아요',
  'intro.body.1': '텍스트와 목소리로 대화하고, 방에서 함께 시간을 보내고, 체스와 익스플로딩 키튼도 먼저 제안하며 즐깁니다.',
  'intro.eyebrow.2': '스스로 이어지는 존재',
  'intro.title.2': '대화 사이에도 생각해요',
  'intro.body.2': 'Rau는 잠든 동안 기억을 돌아보고 정리해, 매일 더 나아지고 맥락을 가지런히 유지합니다.',
  'intro.eyebrow.3': 'Pi 기반 딥 워크',
  'intro.title.3': '필요할 때 여럿이 되어 일해요',
  'intro.body.3': '큰 목표를 작은 계획으로 나누고, 하위 에이전트를 보내 조사하고 만들고 검증한 뒤 하나의 결과로 모읍니다.',
  'setup.progress': '설정 진행 상황',
  'setup.origin': '시작',
  'setup.self': '자아',
  'setup.brains': '두뇌',
  'setup.roles': '역할',
  'setup.voice': '목소리',
  'setup.back': '← 뒤로',
  'setup.continue': '계속 →',
  'setup.bringUp': 'Rau 깨우기',
  'setup.skipVoice': '목소리 건너뛰기',
  'setup.welcomeEyebrow': '다정한 에이전트',
  'setup.welcomeTitle': 'Rau',
  'setup.welcomeBody': '말하고 게임하며, 어려운 일은 워커를 조율해 맡기는 이어지는 존재. 설정에는 약 2분이 걸립니다.',
  'setup.begin': '시작',
  'setup.already': 'Rau가 이미 깨어 있어요 — 대화하기',
  'setup.awake': '깨어남',
  'setup.doneTitle': 'Rau가 준비됐어요',
  'setup.startTalking': 'Rau의 방으로 →',
  'tour.skip': '투어 건너뛰기',
  'tour.next': '다음',
  'tour.finish': '완료',
  'tour.step': '{current} / {total}',
  'tour.room.title': 'Rau의 방',
  'tour.room.body': '여기는 Rau가 머무는 공간이에요. 생각하고, 움직이고, 대화하는 모습을 한곳에서 볼 수 있습니다.',
  'tour.composer.title': '먼저 말을 걸어보세요',
  'tour.composer.body': '입력창을 클릭해 보세요. 지금은 아무것도 보내지 않습니다.',
  'tour.games.title': '함께 놀기',
  'tour.games.body': '체스와 익스플로딩 키튼을 여기서 시작할 수 있어요. Rau도 게임 중 먼저 움직이고 말을 겁니다.',
  'tour.work.title': '딥 워크',
  'tour.work.body': '복잡한 목표는 작업 공간에서 계획, 하위 에이전트, 검증 과정과 함께 진행됩니다.',
  'tour.goal.title': '목표를 맡겨보세요',
  'tour.goal.body': '목표 입력창을 클릭해 보세요. 투어에서는 작업을 시작하지 않습니다.',
  'tour.talk.title': '빠른 대화',
  'tour.talk.body': '기본 화면은 언제든 편하게 이어 말하는 곳이에요. 입력창을 클릭해 보세요.',
  'tour.activity.title': '두 흐름을 따로 보기',
  'tour.activity.body': 'Activity를 열면 메인 에이전트의 대화 활동과 하위 에이전트의 딥 워크 활동을 분리해 볼 수 있어요.',
  'tour.congrats.title': '튜토리얼을 마쳤어요!',
  'tour.congrats.body': '방, 작업, 대화까지 둘러봤어요. 이제 함께 시작해요.',
  'tour.congrats.begin': '시작해요!',
  'settings.experience': '경험',
  'settings.language': '언어',
  'settings.languageHelp': '화면 언어와 Rau가 답하는 언어를 함께 바꿉니다.',
  'settings.replay': '튜토리얼 다시 보기',
  'settings.replayHelp': 'Room → Work → Talk 안내를 처음부터 다시 시작합니다.',
  'settings.saved': '언어가 저장되었습니다.',
  'common.english': 'English',
  'common.korean': '한국어',
  'talk.openRoom': '방 열기 →',
  'talk.activity': '활동',
  'talk.placeholder': 'Rau에게 말해 보세요…',
  'talk.send': '보내기',
  'face.back': '← Rau',
  'face.chess': '체스',
  'face.play': '게임',
  'face.direct': '직접 조작',
  'face.say': 'Rau에게 말해 보세요…',
  'face.hideChat': '대화 숨기기',
  'dashboard.presence': '현재 상태',
  'dashboard.deepWork': '딥 워크',
  'dashboard.newGoal': '새 목표',
  'dashboard.goalPlaceholder': 'Rau가 무엇을 깊이 파고들까요?',
  'dashboard.start': '딥 워크 시작',
  'dashboard.cancel': '취소',
  'activity.label': '활동',
  'activity.off': '끔',
  'permissions.title': '권한',
  'permissions.auto': '자동',
  'permissions.autoDetail': '확인이 필요한 작업은 물어봅니다',
  'permissions.bypass': '완전 우회',
  'permissions.bypassDetail': '어떤 작업도 묻지 않고 실행합니다',
  'permissions.readonly': '읽기 전용',
  'permissions.readonlyDetail': '쓰기, 셸, 외부 변경을 허용하지 않습니다',
} as const

export type TranslationKey = keyof typeof ko

type LocaleContextValue = {
  locale: Locale
  hasChosenLocale: boolean
  setLocale: (locale: Locale) => Promise<void>
  t: (key: TranslationKey, values?: Record<string, string | number>) => string
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

function storedLocale(): Locale | null {
  try {
    const value = localStorage.getItem(LOCALE_KEY)
    return value === 'ko' || value === 'en' ? value : null
  } catch {
    return null
  }
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const initial = storedLocale()
  const [locale, setLocaleState] = useState<Locale>(initial || 'en')
  const [hasChosenLocale, setHasChosenLocale] = useState(initial !== null)

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  useEffect(() => {
    api
      .getLanguage()
      .then((result) => {
        if (!result.configured || storedLocale()) return
        setLocaleState(result.language)
        setHasChosenLocale(true)
        try {
          localStorage.setItem(LOCALE_KEY, result.language)
        } catch {
          /* in-memory locale remains valid */
        }
      })
      .catch(() => {})
  }, [])

  const setLocale = useCallback(async (next: Locale) => {
    setLocaleState(next)
    setHasChosenLocale(true)
    document.documentElement.lang = next
    try {
      localStorage.setItem(LOCALE_KEY, next)
    } catch {
      /* backend remains the durable copy */
    }
    await api.putLanguage(next)
  }, [])

  const t = useCallback(
    (key: TranslationKey, values: Record<string, string | number> = {}) => {
      let text = locale === 'ko' ? ko[key] : EN[key]
      for (const [name, value] of Object.entries(values)) {
        text = text.replaceAll(`{${name}}`, String(value))
      }
      return text
    },
    [locale],
  )

  const value = useMemo(
    () => ({ locale, hasChosenLocale, setLocale, t }),
    [hasChosenLocale, locale, setLocale, t],
  )
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale() {
  const value = useContext(LocaleContext)
  if (!value) throw new Error('useLocale must be used inside LocaleProvider')
  return value
}

const EN: Record<TranslationKey, string> = {
  'nav.talk': 'Talk',
  'nav.face': 'Room',
  'nav.dashboard': 'Work',
  'nav.operations': 'Operations',
  'nav.identity': 'Identity',
  'nav.settings': 'Settings',
  'boot.unreachable': 'Can’t reach the hub',
  'boot.retry': 'Try again',
  'boot.waking': 'waking up',
  'language.title': 'Choose your language',
  'language.lede': 'You can change Rau’s interface and reply language later in Settings.',
  'language.english': 'English',
  'language.englishNote': 'Continue in English',
  'language.korean': '한국어',
  'language.koreanNote': '한국어로 계속하기',
  'intro.skip': 'Skip',
  'intro.back': 'Back',
  'intro.continue': 'Continue',
  'intro.begin': 'Begin setup',
  'intro.eyebrow.1': 'Friendly chat companion',
  'intro.title.1': 'Talk, spend time, and play',
  'intro.body.1': 'Chat by text or voice, share a room, and play chess or Exploding Kittens with Rau as a proactive companion.',
  'intro.eyebrow.2': 'Proactive dreaming',
  'intro.title.2': 'Thinking between conversations',
  'intro.body.2': 'While Rau sleeps, memories are reflected and rearranged, helping Rau improve every day while keeping his context organized.',
  'intro.eyebrow.3': 'Pi-powered deep work',
  'intro.title.3': 'One mind, many helping hands',
  'intro.body.3': 'Large goals become plans. Subagents research, build, and verify in parallel, then return one coherent result.',
  'setup.progress': 'Setup progress',
  'setup.origin': 'Origin',
  'setup.self': 'Self',
  'setup.brains': 'Brains',
  'setup.roles': 'Roles',
  'setup.voice': 'Voice',
  'setup.back': '← Back',
  'setup.continue': 'Continue →',
  'setup.bringUp': 'Bring Rau up',
  'setup.skipVoice': 'Skip voice',
  'setup.welcomeEyebrow': 'Friendly agent',
  'setup.welcomeTitle': 'Rau',
  'setup.welcomeBody':
    'One continuous presence that talks and plays games with you while orchestrating workers to do hard work. Setting this up takes about two minutes.',
  'setup.begin': 'Begin',
  'setup.already': 'Rau is already up — go talk',
  'setup.awake': 'Awake',
  'setup.doneTitle': 'Rau is up',
  'setup.startTalking': 'Enter Rau’s room →',
  'tour.skip': 'Skip tour',
  'tour.next': 'Next',
  'tour.finish': 'Finish',
  'tour.step': '{current} of {total}',
  'tour.room.title': 'Rau’s room',
  'tour.room.body': 'This is where Rau lives. You can see Rau think, move, and talk in one continuous space.',
  'tour.composer.title': 'Say something first',
  'tour.composer.body': 'Click the composer. The tour will not send anything.',
  'tour.games.title': 'Play together',
  'tour.games.body': 'Start chess or Exploding Kittens here. Rau can move and speak proactively during a game.',
  'tour.work.title': 'Deep work',
  'tour.work.body': 'Complex goals unfold here with plans, subagents, progress, and verification.',
  'tour.goal.title': 'Hand over a goal',
  'tour.goal.body': 'Click the goal field. The tour will not start a job.',
  'tour.talk.title': 'Fast conversation',
  'tour.talk.body': 'Talk is the quickest place to continue the thread at any time. Click the composer.',
  'tour.activity.title': 'See both streams',
  'tour.activity.body': 'Open Activity to switch between the main agent’s conversation work and subagent Deep Work.',
  'tour.congrats.title': 'Congrats on your tutorial!',
  'tour.congrats.body': 'You’ve seen the room, the workbench, and the talk thread. Now it’s yours.',
  'tour.congrats.begin': 'Let’s begin!',
  'settings.experience': 'Experience',
  'settings.language': 'Language',
  'settings.languageHelp': 'Changes both the interface and the language Rau replies in.',
  'settings.replay': 'Replay tutorial',
  'settings.replayHelp': 'Restart the Room → Work → Talk walkthrough.',
  'settings.saved': 'Language saved.',
  'common.english': 'English',
  'common.korean': '한국어',
  'talk.openRoom': 'Open the room →',
  'talk.activity': 'Activity',
  'talk.placeholder': 'Say something to Rau…',
  'talk.send': 'Send',
  'face.back': '← Rau',
  'face.chess': 'Chess',
  'face.play': 'Play',
  'face.direct': 'Direct',
  'face.say': 'Say something to Rau…',
  'face.hideChat': 'Hide chat',
  'dashboard.presence': 'Presence',
  'dashboard.deepWork': 'Deep work',
  'dashboard.newGoal': 'New goal',
  'dashboard.goalPlaceholder': 'What should Rau dig into?',
  'dashboard.start': 'Start deep work',
  'dashboard.cancel': 'Cancel',
  'activity.label': 'Activity',
  'activity.off': 'off',
  'permissions.title': 'Permissions',
  'permissions.auto': 'Auto',
  'permissions.autoDetail': 'Ask when something needs confirmation',
  'permissions.bypass': 'Full bypass',
  'permissions.bypassDetail': 'Run without asking — full trust',
  'permissions.readonly': 'Read only',
  'permissions.readonlyDetail': 'No writes, shell, or side effects',
}
