export type PasswordRule = {
  id: 'length' | 'letters' | 'numbers' | 'characters'
  label: string
  passed: boolean
}

export type PasswordValidation = {
  isValid: boolean
  rules: PasswordRule[]
}

export function validatePassword(password: string): PasswordValidation {
  const rules: PasswordRule[] = [
    {
      id: 'length',
      label: '长度为 8-128 位',
      passed: password.length >= 8 && password.length <= 128,
    },
    {
      id: 'letters',
      label: '至少包含一个字母',
      passed: /\p{L}/u.test(password),
    },
    {
      id: 'numbers',
      label: '至少包含一个数字',
      passed: /\p{Nd}/u.test(password),
    },
    {
      id: 'characters',
      label: '不包含换行或控制字符',
      passed: !/[\p{Cc}\p{Zl}\p{Zp}]/u.test(password),
    },
  ]

  return {
    isValid: rules.every((rule) => rule.passed),
    rules,
  }
}
