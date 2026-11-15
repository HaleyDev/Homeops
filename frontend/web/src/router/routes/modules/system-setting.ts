import type { RouteRecordRaw } from 'vue-router';

import { $t } from '#/locales';

/** 系统设置：仅超级管理员可管理全局 LLM 配置。 */
const routes: RouteRecordRaw[] = [
  {
    name: 'SystemSetting',
    path: '/system-setting',
    component: () => import('#/views/system-setting/llm-config.vue'),
    meta: {
      authority: ['super'],
      icon: 'lucide:settings-2',
      order: 90,
      title: $t('page.systemSetting'),
    },
  },
];

export default routes;
