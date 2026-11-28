import type { RouteRecordRaw } from 'vue-router';

import { $t } from '#/locales';

/** 系统设置：仅超级管理员可管理全局模型配置和知识库。 */
const routes: RouteRecordRaw[] = [
  {
    name: 'SystemSetting',
    path: '/system-setting',
    redirect: '/system-setting/model-providers',
    meta: {
      authority: ['super'],
      icon: 'lucide:settings-2',
      order: 90,
      title: $t('page.systemSetting'),
    },
    children: [
      {
        name: 'SystemSettingModelProviders',
        path: 'model-providers',
        component: () => import('#/views/system-setting/llm-config.vue'),
        meta: {
          authority: ['super'],
          title: $t('page.modelProviderConfig'),
        },
      },
      {
        name: 'SystemSettingKnowledgeBase',
        path: 'knowledge-base',
        component: () => import('#/views/system-setting/knowledge-base.vue'),
        meta: {
          authority: ['super'],
          title: $t('page.knowledgeBaseSetting'),
        },
      },
    ],
  },
];

export default routes;
