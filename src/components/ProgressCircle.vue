<template>
  <svg
    version="1.1"
    xmlns="http://www.w3.org/2000/svg"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    x="0px"
    y="0px"
    style="display: none"
  >
    <symbol id="wave">
      <path
        d="M420,20c21.5-0.4,38.8-2.5,51.1-4.5c13.4-2.2,26.5-5.2,27.3-5.4C514,6.5,518,4.7,528.5,2.7c7.1-1.3,17.9-2.8,31.5-2.7c0,0,0,0,0,0v20H420z"
      ></path>
      <path
        d="M420,20c-21.5-0.4-38.8-2.5-51.1-4.5c-13.4-2.2-26.5-5.2-27.3-5.4C326,6.5,322,4.7,311.5,2.7C304.3,1.4,293.6-0.1,280,0c0,0,0,0,0,0v20H420z"
      ></path>
      <path
        d="M140,20c21.5-0.4,38.8-2.5,51.1-4.5c13.4-2.2,26.5-5.2,27.3-5.4C234,6.5,238,4.7,248.5,2.7c7.1-1.3,17.9-2.8,31.5-2.7c0,0,0,0,0,0v20H140z"
      ></path>
      <path
        d="M140,20c-21.5-0.4-38.8-2.5-51.1-4.5c-13.4-2.2-26.5-5.2-27.3-5.4C46,6.5,42,4.7,31.5,2.7C24.3,1.4,13.6-0.1,0,0c0,0,0,0,0,0l0,20H140z"
      ></path>
    </symbol>
  </svg>
  <div class="progress-wrapper" :class="{ 'completed': isCompleted }">
    <div class="box" :class="boxClass" :style="boxStyle">
      <div class="percent">
        <div class="percentNum" id="count">{{ displayCount }}</div>
        <div class="percentB">%</div>
      </div>
      <div id="water" class="water" :style="waterStyle">
        <svg viewBox="0 0 560 20" class="water_wave water_wave_back">
          <use xlink:href="#wave" :fill="waveBackColor"></use>
        </svg>
        <svg viewBox="0 0 560 20" class="water_wave water_wave_front">
          <use xlink:href="#wave" :fill="waterColor"></use>
        </svg>
      </div>
      <!-- 完成庆祝效果（移到 box 内部，但在百分比下方） -->
      <div v-if="isCompleted" class="celebration">
        <div v-for="i in 12" :key="i" class="particle" :style="getParticleStyle(i)"></div>
      </div>
    </div>
    <!-- 成功图标（独立在外层，覆盖整个圆环） -->
    <div v-if="isCompleted" class="success-icon-wrapper">
      <div class="success-icon">✓</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
const props = defineProps({
  percent: {
    type: Number,
    default: 0
  }
})

const count = ref(0)
const displayCount = ref(0)
const isCompleted = ref(false)
const hasPlayedCompleteAnimation = ref(false)

// 数字滚动动画
const animateCount = (target) => {
  const start = displayCount.value
  const duration = 300 // 300ms
  const startTime = Date.now()

  const animate = () => {
    const now = Date.now()
    const progress = Math.min((now - startTime) / duration, 1)
    const easeOutQuad = 1 - (1 - progress) ** 2 // 缓动函数
    displayCount.value = Math.floor(start + (target - start) * easeOutQuad)

    if (progress < 1) {
      requestAnimationFrame(animate)
    } else {
      displayCount.value = target
    }
  }

  requestAnimationFrame(animate)
}

watch(
  () => props.percent,
  (newVal) => {
    const clamped = Math.min(Math.max(newVal, 0), 100)
    count.value = clamped
    animateCount(clamped)

    // 检测是否完成
    if (clamped >= 100 && !hasPlayedCompleteAnimation.value) {
      hasPlayedCompleteAnimation.value = true
      setTimeout(() => {
        isCompleted.value = true
      }, 300)
    } else if (clamped < 100) {
      isCompleted.value = false
      hasPlayedCompleteAnimation.value = false
    }
  }
)

// 根据进度计算颜色
const waterColor = computed(() => {
  const progress = count.value
  if (progress >= 100) {
    return '#67c23a' // 成功绿色
  } else if (progress >= 70) {
    return '#409eff' // 蓝色
  } else if (progress >= 40) {
    return '#e6a23c' // 橙色
  } else {
    return '#f56c6c' // 红色
  }
})

const waveBackColor = computed(() => {
  const progress = count.value
  if (progress >= 100) {
    return '#b3e19d' // 浅绿
  } else if (progress >= 70) {
    return '#79bbff' // 浅蓝
  } else if (progress >= 40) {
    return '#f3d19e' // 浅橙
  } else {
    return '#fab6b6' // 浅红
  }
})

const waterStyle = computed(() => {
  return {
    transform: `translate(0, ${100 - count.value}%)`,
    background: waterColor.value
  }
})

const boxStyle = computed(() => {
  if (isCompleted.value) {
    return {
      boxShadow: `0 0 30px ${waterColor.value}, 0 0 60px ${waterColor.value}80`
    }
  }
  return {}
})

const boxClass = computed(() => {
  return {
    'box-completed': isCompleted.value
  }
})

// 粒子位置计算
const getParticleStyle = (index) => {
  const angle = (360 / 12) * index
  const rad = (angle * Math.PI) / 180
  const distance = 120
  const x = Math.cos(rad) * distance
  const y = Math.sin(rad) * distance

  return {
    '--x': `${x}px`,
    '--y': `${y}px`,
    animationDelay: `${index * 0.05}s`
  }
}

onMounted(() => {
  count.value = props.percent
  displayCount.value = props.percent
  if (props.percent >= 100) {
    isCompleted.value = true
    hasPlayedCompleteAnimation.value = true
  }
})
</script>
<style scoped lang="scss">
.progress-wrapper {
  position: relative;
  display: inline-block;
}

.box {
  height: 200px;
  width: 200px;
  position: relative;
  background: #020438;
  border-radius: 100%;
  overflow: hidden;
  transition: all 0.6s cubic-bezier(0.4, 0, 0.2, 1);

  &.box-completed {
    animation: complete-bounce 0.8s cubic-bezier(0.68, -0.55, 0.265, 1.55);
  }
}

@media screen and (max-width: 375px) {
  .box {
    height: 150px;
    width: 150px;
  }
}

@media screen and (max-width: 768px) {
  .box {
    height: 200px;
    width: 200px;
  }
}

@media screen and (max-width: 1200) {
  .box {
    height: 600px;
    width: 600px;
  }
}

.box .percent {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 3;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 32px;
  font-weight: 700;

  .percentNum {
    font-variant-numeric: tabular-nums;
    text-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  }
}

.box .water {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 2;
  width: 100%;
  height: 100%;
  transform: translate(0, 100%);
  background: #4d6de3;
  transition: all 0.8s cubic-bezier(0.4, 0, 0.2, 1);
}

.box .water_wave {
  width: 200%;
  position: absolute;
  bottom: 100%;
  transition: fill 0.6s ease;
}

.box .water_wave_back {
  right: 0;
  fill: #c7eeff;
  animation: wave-back 1.4s infinite linear;
}

.box .water_wave_front {
  left: 0;
  fill: #4d6de3;
  margin-bottom: -1px;
  animation: wave-front 0.7s infinite linear;
}

// ========== 庆祝动画 ==========

.celebration {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 1; /* 在水波下方 */
}

.particle {
  position: absolute;
  width: 10px;
  height: 10px;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0.6));
  border-radius: 50%;
  top: 0;
  left: 0;
  animation: particle-explosion 1.2s cubic-bezier(0.4, 0, 0.2, 1) forwards;
  box-shadow: 0 0 15px rgba(255, 255, 255, 0.8);
}

.success-icon-wrapper {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 20; /* 在所有元素上方 */
}

.success-icon {
  font-size: 60px;
  font-weight: bold;
  color: #67c23a;
  text-shadow:
    0 0 20px rgba(103, 194, 58, 0.8),
    0 0 40px rgba(103, 194, 58, 0.6),
    0 2px 8px rgba(0, 0, 0, 0.3);
  animation: success-icon-appear 0.6s 0.3s cubic-bezier(0.68, -0.55, 0.265, 1.55) forwards;
  transform: scale(0);
  opacity: 0;
}

// ========== 动画定义 ==========

@keyframes complete-bounce {
  0% {
    transform: scale(1);
  }
  30% {
    transform: scale(1.15);
  }
  50% {
    transform: scale(0.95);
  }
  70% {
    transform: scale(1.05);
  }
  100% {
    transform: scale(1);
  }
}

@keyframes particle-explosion {
  0% {
    transform: translate(0, 0) scale(0);
    opacity: 1;
  }
  50% {
    opacity: 1;
  }
  100% {
    transform: translate(var(--x), var(--y)) scale(0);
    opacity: 0;
  }
}

@keyframes success-icon-appear {
  0% {
    transform: scale(0) rotate(-180deg);
    opacity: 0;
  }
  60% {
    transform: scale(1.2) rotate(10deg);
    opacity: 1;
  }
  100% {
    transform: scale(1) rotate(0deg);
    opacity: 1;
  }
}

@-webkit-keyframes wave-front {
  100% {
    transform: translate(-50%, 0);
  }
}

@keyframes wave-front {
  100% {
    transform: translate(-50%, 0);
  }
}

@-webkit-keyframes wave-back {
  100% {
    transform: translate(50%, 0);
  }
}

@keyframes wave-back {
  100% {
    transform: translate(50%, 0);
  }
}
</style>
