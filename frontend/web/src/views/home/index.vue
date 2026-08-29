<script lang="ts" setup>
import { IconifyIcon } from '@vben/icons';
import { openWindow } from '@vben/utils';

import { serviceItems } from './services';

/** 点击卡片：新标签页打开对应服务（管理台本身留在当前页） */
function openService(url: string) {
  openWindow(url, { target: '_blank' });
}
</script>

<template>
  <div class="p-5">
    <!-- 页头 -->
    <div class="mb-6">
      <h1 class="text-2xl font-semibold">研发服务</h1>
      <p class="text-muted-foreground mt-2 text-sm">
        常用研发基础设施与工具，点击卡片直达
      </p>
    </div>

    <!-- 服务卡片网格 -->
    <div
      class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
    >
      <div
        v-for="item in serviceItems"
        :key="item.title"
        role="button"
        tabindex="0"
        class="bg-card border-border group relative flex cursor-pointer flex-col items-center justify-center rounded-xl border p-6 shadow-sm transition-all select-none hover:-translate-y-0.5 hover:shadow-lg focus-visible:ring-primary focus-visible:ring-2 focus-visible:outline-none"
        @click="openService(item.url)"
        @keydown.enter="openService(item.url)"
      >
        <!-- 右上角外链指示（悬停时出现） -->
        <IconifyIcon
          class="text-muted-foreground group-hover:text-primary absolute top-4 right-4 size-4 opacity-0 transition-all group-hover:opacity-100"
          icon="lucide:arrow-up-right"
        />

        <div
          class="flex size-12 items-center justify-center rounded-lg"
          :style="{ backgroundColor: `${item.color}1a` }"
        >
          <IconifyIcon
            :color="item.color"
            :icon="item.icon"
            class="size-6 transition-transform duration-300 group-hover:scale-110"
          />
        </div>

        <h3 class="mt-4 text-base font-semibold">{{ item.title }}</h3>
        <p class="text-muted-foreground mt-1 text-center text-sm">
          {{ item.description }}
        </p>
      </div>
    </div>
  </div>
</template>
