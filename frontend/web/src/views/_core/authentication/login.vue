<script lang="ts" setup>
import type { VbenFormSchema } from '@vben/common-ui';

import { computed } from 'vue';

import { AuthenticationLogin, z } from '@vben/common-ui';
import { $t } from '@vben/locales';

import { useAuthStore } from '#/store';

defineOptions({ name: 'Login' });

const authStore = useAuthStore();

const formSchema = computed((): VbenFormSchema[] => {
  return [
    {
      component: 'VbenInput',
      componentProps: {
        placeholder: $t('authentication.usernameTip'),
      },
      fieldName: 'username',
      label: $t('authentication.username'),
      rules: z.string().min(1, { message: $t('authentication.usernameTip') }),
    },
    {
      component: 'VbenInputPassword',
      componentProps: {
        placeholder: $t('authentication.password'),
      },
      fieldName: 'password',
      label: $t('authentication.password'),
      rules: z.string().min(1, { message: $t('authentication.passwordTip') }),
    },
  ];
});
</script>

<template>
  <AuthenticationLogin
    :form-schema="formSchema"
    :loading="authStore.loginLoading"
    :show-code-login="false"
    :show-forget-password="false"
    :show-qrcode-login="false"
    :show-register="false"
    :show-third-party-login="false"
    @submit="authStore.authLogin"
  >
    <!-- GitLab OIDC 登录：普通链接触发浏览器整页跳转（非 AJAX），
         后端 302 到 GitLab 授权页，回调后由前端 /auth/redirect 中转页恢复登录态 -->
    <template #third-party-login>
      <div class="my-3 flex items-center justify-center text-xs">
        <div class="bg-border h-px flex-1"></div>
        <span class="text-muted-foreground px-3">或</span>
        <div class="bg-border h-px flex-1"></div>
      </div>
      <a
        href="/api/oidc/authenticate"
        class="border-border text-foreground hover:bg-accent mb-1 flex h-9 w-full items-center justify-center rounded-md border text-sm font-medium transition-colors"
      >
        <svg viewBox="0 0 24 24" class="mr-2 h-4 w-4" aria-hidden="true">
          <path
            fill="#e24329"
            d="M12 2.7 8.4 8.2h7.2L12 2.7zM5.5 8.2 2 12.6h4.4l-.9-4.4zM18.5 8.2l-.9 4.4H22l-3.5-4.4z"
          />
          <path
            fill="#fc6d26"
            d="m12 2.7-3.6 5.5H5.5L12 2.7zm6.5 5.5h-2.9L12 2.7l3.6 5.5zM8.4 8.2 6.4 15h11.2l-2-6.8H8.4z"
          />
          <path
            fill="#fca326"
            d="M2 12.6 6.4 15 8.4 8.2 2 12.6zm20 0L15.6 8.2l2 6.8H22z"
          />
        </svg>
        使用 GitLab 登录
      </a>
    </template>
  </AuthenticationLogin>
</template>
