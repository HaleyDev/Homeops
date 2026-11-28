import type { RouteRecordRaw } from 'vue-router';

import { $t } from '#/locales';

/** Skill Hub：所有登录用户均可上传和查看，所有权由后端复核。 */
const routes: RouteRecordRaw[] = [
  {
    name: 'SkillHub',
    path: '/skill-hub',
    component: () => import('#/views/skill-hub/index.vue'),
    meta: {
      icon: 'lucide:package-open',
      order: 20,
      title: $t('page.skillHub'),
    },
  },
];

export default routes;
