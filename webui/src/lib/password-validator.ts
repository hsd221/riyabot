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
      label: '长度为 8-16 位',
      passed: password.length >= 8 && password.length <= 16,
    },
    {
      id: 'letters',
      label: '至少包含一个英文字母',
      passed: /[A-Za-z]/.test(password),
    },
    {
      id: 'numbers',
      label: '至少包含一个数字',
      passed: /[0-9]/.test(password),
    },
    {
      id: 'characters',
      label: '仅使用英文字母和数字',
      passed: /^[A-Za-z0-9]*$/.test(password),
    },
  ]

  return {
    isValid: rules.every((rule) => rule.passed),
    rules,
  }
}
