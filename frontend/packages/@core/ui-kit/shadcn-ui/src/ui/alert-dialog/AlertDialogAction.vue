<template>
  <AlertDialogAction v-bind="props">
    <slot></slot>
  </AlertDialogAction>
</template>

<script setup lang="ts">
import type { AlertDialogActionProps } from 'reka-ui';

import { AlertDialogAction } from 'reka-ui';

const props = defineProps<AlertDialogActionProps>();
</script>
