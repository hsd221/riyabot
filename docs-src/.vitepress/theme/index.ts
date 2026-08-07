import DefaultTheme from 'vitepress/theme'
import { h } from 'vue'
import HomeField from './HomeField.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  Layout() {
    return h(DefaultTheme.Layout, null, {
      'home-hero-before': () => h(HomeField),
    })
  },
  enhanceApp() {
    if (typeof document !== 'undefined') {
      document.documentElement.dataset.arkTheme = 'endfield'
      document.documentElement.dataset.arkDepth = 'maximal'
    }
  },
}
