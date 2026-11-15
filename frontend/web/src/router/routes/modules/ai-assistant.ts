import type { RouteRecordRaw } from 'vue-router';

import { $t } from '#/locales';

/** AI 助手:对话式运维助手 */
const routes: RouteRecordRaw[] = [
  {
    name: 'AiAssistant',
    path: '/ai-assistant',
    component: () => import('#/views/ai-assistant/index.vue'),
    meta: {
      icon: 'lucide:bot',
      order: 0,
      title: $t('page.aiAssistant'),
    },
  },
];

export default routes;
