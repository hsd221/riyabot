import { describe, expect, it } from 'bun:test'

import { validatePassword } from '../src/lib/password-validator'

describe('password validation', () => {
  it('accepts long passphrases, symbols, and Unicode while preserving composition requirements', () => {
    expect(validatePassword('correct horse battery staple 7!').isValid).toBe(true)
    expect(validatePassword('璃夜安全密码123!').isValid).toBe(true)
    expect(validatePassword(`A1${'x'.repeat(126)}`).isValid).toBe(true)
  })

  it('rejects control characters, missing composition, and values over 128 characters', () => {
    expect(validatePassword('abcdefgh').isValid).toBe(false)
    expect(validatePassword('12345678').isValid).toBe(false)
    expect(validatePassword('abc1234\n').isValid).toBe(false)
    expect(validatePassword('abc1234\u2028').isValid).toBe(false)
    expect(validatePassword(`A1${'x'.repeat(127)}`).isValid).toBe(false)
  })
})
