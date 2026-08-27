import { defineConfig } from '@vben/vite-config';

export default defineConfig(async () => {
  return {
    application: {},
    vite: {
      server: {
        proxy: {
          '/api': {
            changeOrigin: true,
            // Django 后端（Homeops），保留 /api 前缀
            target: 'http://localhost:8000',
            ws: true,
          },
        },
      },
    },
  };
});
