/**
 * 研发服务入口配置
 *
 * 新增服务：在数组里加一项即可，首页卡片会自动渲染。
 * icon 为内嵌官方 logo 的 Iconify 图标对象（离线渲染，无需联网加载图标库），
 * color 为品牌标准色，用于图标着色和浅色背景。
 */

/** Iconify 图标对象（结构与 @iconify/vue 的 IconifyIcon 兼容） */
interface ServiceIcon {
  body: string;
  height: number;
  width: number;
}

interface ServiceItem {
  /** 品牌标准色（hex） */
  color: string;
  /** 图标（内嵌 SVG 的 Iconify 图标对象） */
  icon: ServiceIcon;
  /** 一句话描述 */
  description: string;
  /** 服务名称 */
  title: string;
  /** 服务地址（点击卡片在新标签页打开） */
  url: string;
}

/** GitLab 官方 logo（simple-icons，品牌色 #FC6D26） */
const gitlabLogo: ServiceIcon = {
  body: '<path fill="currentColor" d="m23.6 9.593l-.033-.086L20.3.98a.85.85 0 0 0-.336-.405a.875.875 0 0 0-1 .054a.9.9 0 0 0-.29.44L16.47 7.818H7.537L5.333 1.07a.86.86 0 0 0-.29-.441a.875.875 0 0 0-1-.054a.86.86 0 0 0-.336.405L.433 9.502l-.032.086a6.066 6.066 0 0 0 2.012 7.01l.01.009l.03.021l4.977 3.727l2.462 1.863l1.5 1.132a1.01 1.01 0 0 0 1.22 0l1.499-1.132l2.461-1.863l5.006-3.75l.013-.01a6.07 6.07 0 0 0 2.01-7.002"/>',
  height: 24,
  width: 24,
};

/** Harbor 官方 logo（simple-icons，品牌色 #60B932） */
const harborLogo: ServiceIcon = {
  body: '<path fill="currentColor" d="m7.006 15.751l4.256 1.876l.066.805l-4.388-1.934zm.304-3.435h-.605V11.21h.381V8.95h-.381v-.649l2.118-2.073v-.146c0-.11.09-.2.2-.2s.2.09.2.2v.146l2.12 2.073v.65h-.382v2.259h.381v1.106h-.514l.27 3.313L7.17 13.9zm.39-1.106h.628v-.965c0-.383.313-.696.695-.696s.696.313.696.696v.965h.628V8.95H7.7zm-.81 5.84l-.066.747l4.618 2.035l-.066-.805zm.23-2.6l-.066.747l4.158 1.832l-.065-.805l-4.026-1.774zM24 12c0 6.617-5.383 12-12 12S0 18.617 0 12S5.383 0 12 0s12 5.383 12 12m-2.43-.715a10 10 0 0 0-.223-1.523l-9.751.332l8.801-2.828l-.019-.037A9.8 9.8 0 0 0 19.23 5.59l-7.786 4.03l5.712-5.941a9.7 9.7 0 0 0-5.14-1.474c-5.371 0-9.74 4.369-9.74 9.74a9.74 9.74 0 0 0 4.35 8.11l.151-1.704l4.715 2.078l.102 1.246q.21.01.422.01c4.646 0 8.54-3.27 9.507-7.63l-10.08-3.497z"/>',
  height: 24,
  width: 24,
};

export const serviceItems: ServiceItem[] = [
  {
    title: 'GitLab',
    description: '代码仓库 · CI/CD',
    icon: gitlabLogo,
    color: '#FC6D26',
    url: 'http://192.168.199.123:9090',
  },
  {
    title: 'Harbor',
    description: 'Docker 镜像仓库',
    icon: harborLogo,
    color: '#60B932',
    url: 'http://192.168.199.123:2233',
  },
];
