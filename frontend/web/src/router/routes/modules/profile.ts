import type { RouteRecordRaw } from 'vue-router';

import { $t } from '#/locales';

/** 个人资料页（从原 vben.ts 中拆出，用户下拉菜单在用） */
const routes: RouteRecordRaw[] = [
  {
    name: 'Profile',
    path: '/profile',
    component: () => import('#/views/_core/profile/index.vue'),
    meta: {
      icon: 'lucide:user',
      hideInMenu: true,
      title: $t('page.auth.profile'),
    },
  },
];

export default routes;
