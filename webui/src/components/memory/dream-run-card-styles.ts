import type { DreamPhaseCode } from './dream-run-summary'

export const RUN_TYPE_CLASSES: Record<string, string> = {
  daily:
    'bg-[rgb(0_122_255_/_0.12)] text-[rgb(0_84_166)] dark:bg-[rgb(10_132_255_/_0.18)] dark:text-[rgb(100_210_255)]',
  weekly:
    'bg-[rgb(88_86_214_/_0.12)] text-[rgb(54_52_163)] dark:bg-[rgb(191_90_242_/_0.18)] dark:text-[rgb(191_90_242)]',
  monthly:
    'bg-[rgb(255_149_0_/_0.14)] text-[rgb(172_96_0)] dark:bg-[rgb(255_159_10_/_0.2)] dark:text-[rgb(255_159_10)]',
}

export const PHASE_CLASSES: Record<DreamPhaseCode, string> = {
  N2: 'bg-[rgb(0_122_255_/_0.12)] text-[rgb(0_84_166)] dark:bg-[rgb(10_132_255_/_0.18)] dark:text-[rgb(100_210_255)]',
  N3: 'bg-[rgb(88_86_214_/_0.12)] text-[rgb(54_52_163)] dark:bg-[rgb(191_90_242_/_0.18)] dark:text-[rgb(191_90_242)]',
  REM: 'bg-[rgb(255_149_0_/_0.14)] text-[rgb(172_96_0)] dark:bg-[rgb(255_159_10_/_0.2)] dark:text-[rgb(255_159_10)]',
}
