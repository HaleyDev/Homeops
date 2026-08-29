<script lang="ts" setup>
import { onMounted } from 'vue';
import { useRouter } from 'vue-router';

import { LOGIN_PATH } from '@vben/constants';
import { preferences } from '@vben/preferences';
import { useAccessStore } from '@vben/stores';

import { notification } from '#/adapter/naive';
import { getAccessCodesApi, refreshTokenApi } from '#/api';
import { useAuthStore } from '#/store';

/**
 * GitLab OIDC 登录中转页（/auth/redirect）
 *
 * 后端处理完 GitLab 回调后 302 到本页面：
 * - 成功：refresh token 已写入 HttpOnly Cookie（path=/api/auth）
 * - 失败：URL 带 ?error= 参数
 *
 * 本页职责：用 Cookie 换取 accessToken，拉取用户信息与权限码，
 * 完成"无感登录"后跳转首页；任何一步失败则回到登录页。
 */
defineOptions({ name: 'AuthRedirect' });

const router = useRouter();
const accessStore = useAccessStore();
const authStore = useAuthStore();

onMounted(async () => {
  // 后端明确告知失败（GitLab 拒绝授权、code 过期等）
  const error = new URLSearchParams(window.location.search).get('error');
  if (error) {
    await toLogin('GitLab 登录失败，请重试或改用账号密码登录');
    return;
  }

  try {
    // 与 authStore.authLogin 后半段相同的登录态恢复流程
    const { data: accessToken } = await refreshTokenApi();
    if (!accessToken) {
      throw new Error('refresh token 无效');
    }
    accessStore.setAccessToken(accessToken);

    const [userInfo, accessCodes] = await Promise.all([
      authStore.fetchUserInfo(),
      getAccessCodesApi(),
    ]);
    accessStore.setAccessCodes(accessCodes);

    await router.replace(
      userInfo.homePath || preferences.app.defaultHomePath,
    );
  } catch {
    // 换 token 失败（Cookie 缺失/过期），退回登录页
    await toLogin('登录状态已失效，请重新登录');
  }
});

async function toLogin(message: string) {
  notification.error({
    content: '登录失败',
    description: message,
    duration: 3000,
  });
  await router.replace({ path: LOGIN_PATH });
}
</script>

<template>
  <div class="flex min-h-[100dvh] w-full flex-col items-center justify-center gap-4">
    <div
      class="border-primary h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
    ></div>
    <p class="text-muted-foreground text-sm">正在完成 GitLab 登录…</p>
  </div>
</template>
