/** Widget 注册表：id → 组件。新增 Widget 只需在此登记。 */

import type { Component } from 'vue'

import AiQuickWidget from './AiQuickWidget.vue'
import CurrentProjectWidget from './CurrentProjectWidget.vue'
import DeviceStatusWidget from './DeviceStatusWidget.vue'
import FrequentAppsWidget from './FrequentAppsWidget.vue'
import LearningProgressWidget from './LearningProgressWidget.vue'
import WeatherWidget from './WeatherWidget.vue'
import WorkModeWidget from './WorkModeWidget.vue'
import FallbackWidget from './FallbackWidget.vue'

export const widgetRegistry: Record<string, Component> = {
  'work-mode': WorkModeWidget,
  'current-project': CurrentProjectWidget,
  'ai-quick': AiQuickWidget,
  'frequent-apps': FrequentAppsWidget,
  'learning-progress': LearningProgressWidget,
  weather: WeatherWidget,
  'device-status': DeviceStatusWidget,
  fallback: FallbackWidget,
}
