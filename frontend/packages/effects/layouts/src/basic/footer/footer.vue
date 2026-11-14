<template>
  <div class="relative flex-center size-full text-xs text-muted-foreground">
    <slot></slot>
  </div>
</template>

<script lang="ts" setup>
defineOptions({
  name: 'LayoutFooter',
});
</script>
