import type { RouteRecordRaw } from 'vue-router';

import { $t } from '#/locales';

/** 首页：内网服务入口卡片 */
const routes: RouteRecordRaw[] = [
  {
    name: 'Home',
    path: '/home',
    component: () => import('#/views/home/index.vue'),
    meta: {
      icon: 'lucide:home',
      order: -2,
      title: $t('page.home.title'),
    },
  },
];

export default routes;
