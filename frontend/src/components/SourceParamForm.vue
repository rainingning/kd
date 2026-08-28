<template>
  <div class="source-form" :class="{ readonly }">
    <el-alert v-if="errorList.length" type="error" :closable="false" class="error-summary">
      <template #title>发现 {{ errorList.length }} 处问题，请检查标红字段</template>
      <ul><li v-for="item in errorList.slice(0, 10)" :key="item.path">{{ item.path }}：{{ item.message }}</li></ul>
    </el-alert>

    <el-card v-if="isBe" shadow="never" class="section-card">
      <template #header><SectionTitle title="后退欧拉时间参数" hint="每个时间块的步长按 2 倍递增" /></template>
      <el-row :gutter="16">
        <el-col :xs="24" :sm="8"><NumberInput label="时间块数 nblock" unit="个" integer :value="get(timePath, 'blocks')" :disabled="readonly" :error="fieldError(`${timePath}.blocks`)" @change="setField(timePath, 'blocks', $event)" /></el-col>
        <el-col :xs="24" :sm="8"><NumberInput label="每块步数 nstep" unit="步" integer :value="get(timePath, 'steps_per_block')" :disabled="readonly" :error="fieldError(`${timePath}.steps_per_block`)" @change="setField(timePath, 'steps_per_block', $event)" /></el-col>
        <el-col :xs="24" :sm="8"><NumberInput label="基础步长 dt0" unit="s" :value="get(timePath, 'base_time_step')" :disabled="readonly" :error="fieldError(`${timePath}.base_time_step`)" @change="setField(timePath, 'base_time_step', $event)" /></el-col>
      </el-row>
    </el-card>

    <el-card v-else shadow="never" class="section-card">
      <template #header><SectionTitle title="频率与线性求解器" hint="频率点在最小值和最大值之间按对数等间隔生成" /></template>
      <el-row :gutter="16">
        <el-col :xs="24" :sm="8"><NumberInput label="频点数 nfreq" unit="个" integer :value="get(frequencyPath, frequencyKeys.count)" :disabled="readonly" :error="fieldError(`${frequencyPath}.${frequencyKeys.count}`)" @change="setField(frequencyPath, frequencyKeys.count, $event)" /></el-col>
        <el-col :xs="24" :sm="8"><NumberInput label="最小频率 fmin" unit="Hz" :value="get(frequencyPath, frequencyKeys.min)" :disabled="readonly" :error="fieldError(`${frequencyPath}.${frequencyKeys.min}`)" @change="setField(frequencyPath, frequencyKeys.min, $event)" /></el-col>
        <el-col :xs="24" :sm="8"><NumberInput label="最大频率 fmax" unit="Hz" :value="get(frequencyPath, frequencyKeys.max)" :disabled="readonly" :error="fieldError(`${frequencyPath}.${frequencyKeys.max}`)" @change="setField(frequencyPath, frequencyKeys.max, $event)" /></el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="求解器" :error="fieldError(`${solverPath}.${solverKeys.mode}`)">
            <el-select :model-value="get(solverPath, solverKeys.mode)" :disabled="readonly" @update:model-value="setField(solverPath, solverKeys.mode, $event)">
              <el-option label="1 — Direct 直接法" :value="1" /><el-option label="2 — Rational Krylov" :value="2" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12"><NumberInput label="RK 子空间维数" unit="维" integer :value="get(solverPath, solverKeys.dimension)" :disabled="readonly" :error="fieldError(`${solverPath}.${solverKeys.dimension}`)" @change="setField(solverPath, solverKeys.dimension, $event)" /></el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header><SectionTitle title="空气域与材料" hint="材料 ID 必须对应 mesh.mphtxt 的 Domain ID" /></template>
      <el-form-item label="空气域 ID" :error="fieldError('air_domain_ids')">
        <el-select :model-value="doc.air_domain_ids || []" multiple allow-create filterable default-first-option :disabled="readonly" placeholder="输入整数后回车" @update:model-value="setAirIds">
          <el-option v-for="id in (doc.air_domain_ids || [])" :key="id" :label="String(id)" :value="id" />
        </el-select>
      </el-form-item>
      <div class="section-head"><strong>材料表（{{ materials.length }}）</strong><el-button v-if="!readonly" type="primary" plain @click="addMaterial">新增材料</el-button></div>
      <el-empty v-if="!materials.length" description="暂无材料" />
      <div v-for="(mat, mi) in materials" :key="mi" class="item-block">
        <div class="item-head"><strong>材料 {{ mi + 1 }}</strong><div v-if="!readonly"><el-button link type="primary" @click="copyMaterial(mi)">复制</el-button><el-button link type="danger" @click="removeMaterial(mi)">删除</el-button></div></div>
        <el-row :gutter="12">
          <el-col :xs="12" :sm="6" :md="3"><NumberInput label="ID" integer :value="mat.id" :disabled="readonly" :error="fieldError(`materials.${mi}.id`)" @change="setArrayField(materialsPath, mi, 'id', $event)" /></el-col>
          <el-col v-for="axis in ['x','y','z']" :key="axis" :xs="12" :sm="6" :md="3"><NumberInput :label="`ρ${axis}`" unit="Ω·m" :value="mat[`rho_${axis}`]" :disabled="readonly" :error="fieldError(`materials.${mi}.rho_${axis}`)" @change="setArrayField(materialsPath, mi, `rho_${axis}`, $event)" /></el-col>
          <el-col v-for="angle in ['alpha','beta','gamma']" :key="angle" :xs="12" :sm="6" :md="3"><NumberInput :label="angle" unit="°" :value="mat[angle]" :disabled="readonly" :error="fieldError(`materials.${mi}.${angle}`)" @change="setArrayField(materialsPath, mi, angle, $event)" /></el-col>
          <el-col :xs="12" :sm="6" :md="3"><NumberInput label="μr" :value="mat.mu_r" :disabled="readonly" :error="fieldError(`materials.${mi}.mu_r`)" @change="setArrayField(materialsPath, mi, 'mu_r', $event)" /></el-col>
          <el-col v-if="isBe" :xs="12" :sm="6" :md="3"><NumberInput label="εr" :value="mat.epsilon_r" :disabled="readonly" :error="fieldError(`materials.${mi}.epsilon_r`)" @change="setArrayField(materialsPath, mi, 'epsilon_r', $event)" /></el-col>
        </el-row>
      </div>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header><SectionTitle :title="isLoop ? '闭合多边形回线源' : '接地导线源'" :hint="isLoop ? '正电流按顶点列出顺序并由末点闭合到首点' : '正电流沿每条线段的起点指向终点'" /></template>
      <el-row :gutter="16">
        <el-col :xs="24" :sm="isLoop ? 12 : 24"><NumberInput label="电流幅值" unit="A" :value="doc.source?.current" :disabled="readonly" :error="fieldError('source.current')" @change="updatePath('source.current', $event)" /></el-col>
        <el-col v-if="isLoop" :xs="24" :sm="12"><NumberInput label="回线匝数" unit="匝" integer :value="doc.source?.turns" :disabled="readonly" :error="fieldError('source.turns')" @change="updatePath('source.turns', $event)" /></el-col>
      </el-row>

      <template v-if="!isLoop">
        <div class="section-head"><strong>导线线段（{{ segments.length }}）</strong><el-button v-if="!readonly" type="primary" plain @click="addSegment">新增线段</el-button></div>
        <el-empty v-if="!segments.length" description="暂无导线线段" />
        <div v-for="(segment, si) in segments" :key="si" class="geometry-row">
          <div class="geometry-title"><strong>线段 {{ si + 1 }}</strong><el-button v-if="!readonly" link type="danger" @click="removeArrayItem(segmentsPath, si)">删除</el-button></div>
          <PointInput label="起点" :value="segmentPoint(segment, true)" :disabled="readonly" :error-at="axis => pointError(`${segmentsPath}.${si}.${segmentPointKey(segment, true)}`, axis)" @change="setSegmentPoint(si, true, $event)" />
          <PointInput label="终点" :value="segmentPoint(segment, false)" :disabled="readonly" :error-at="axis => pointError(`${segmentsPath}.${si}.${segmentPointKey(segment, false)}`, axis)" @change="setSegmentPoint(si, false, $event)" />
        </div>
      </template>
      <template v-else>
        <div class="section-head"><strong>多边形顶点（{{ vertices.length }}）</strong><el-button v-if="!readonly" type="primary" plain @click="appendArray(verticesPath, pointZero())">新增顶点</el-button></div>
        <el-empty v-if="!vertices.length" description="暂无回线顶点" />
        <div v-for="(point, pi) in vertices" :key="pi" class="geometry-row compact">
          <div class="geometry-title"><strong>顶点 {{ pi + 1 }}</strong><el-button v-if="!readonly" link type="danger" @click="removeArrayItem(verticesPath, pi)">删除</el-button></div>
          <PointInput :value="point" :disabled="readonly" :error-at="axis => pointError(`${verticesPath}.${pi}`, axis)" @change="setArrayItem(verticesPath, pi, $event)" />
        </div>
      </template>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header><div class="section-head"><SectionTitle title="接收点" hint="坐标必须位于四面体网格覆盖范围内，单位 m" /><el-button v-if="!readonly" type="primary" plain @click="appendArray(receiversPath, pointZero())">新增接收点</el-button></div></template>
      <el-empty v-if="!receivers.length" description="暂无接收点" />
      <div v-for="(point, ri) in receivers" :key="ri" class="geometry-row compact">
        <div class="geometry-title"><strong>接收点 {{ ri + 1 }}</strong><el-button v-if="!readonly" link type="danger" @click="removeArrayItem(receiversPath, ri)">删除</el-button></div>
        <PointInput :value="point" :disabled="readonly" :error-at="axis => pointError(`${receiversPath}.${ri}`, axis)" @change="setArrayItem(receiversPath, ri, $event)" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, ref, watch } from 'vue'
import { ElFormItem, ElInputNumber } from 'element-plus'

const props = defineProps({ modelValue: { type: Object, default: () => ({}) }, programKey: { type: String, required: true }, sourceType: { type: String, required: true }, readonly: Boolean, errors: { type: [Array, Object], default: () => [] } })
const emit = defineEmits(['update:modelValue'])
const localErrors = ref([])
const doc = computed(() => props.modelValue || {})
const isBe = computed(() => props.programKey === 'be_fetd')
const isLoop = computed(() => props.sourceType === 'loop')

const SectionTitle = defineComponent({
  props: { title: String, hint: String },
  setup(p) {
    return () => h('div', { class: 'section-title' }, [h('span', p.title), h('small', p.hint)])
  },
})
const NumberInput = defineComponent({
  props: { label: String, value: Number, unit: String, disabled: Boolean, integer: Boolean, error: String },
  emits: ['change'],
  setup(p, { emit: out }) {
    return () => h(ElFormItem, { label: p.label, error: p.error }, {
      default: () => [
        h(ElInputNumber, {
          modelValue: p.value,
          disabled: p.disabled,
          precision: p.integer ? 0 : undefined,
          step: p.integer ? 1 : undefined,
          controlsPosition: 'right',
          style: 'width:100%',
          'onUpdate:modelValue': value => out('change', value),
        }),
        p.unit ? h('div', { class: 'hint' }, `单位：${p.unit}`) : null,
      ],
    })
  },
})
const PointInput = defineComponent({
  props: { label: String, value: Object, disabled: Boolean, errorAt: Function },
  emits: ['change'],
  setup(p, { emit: out }) {
    return () => h('div', { class: 'point' }, [
      p.label ? h('div', { class: 'point-label' }, `${p.label}（m）`) : null,
      h('div', { class: 'point-grid' }, ['x', 'y', 'z'].map(axis =>
        h(ElFormItem, { error: p.errorAt?.(axis) }, {
          default: () => h(ElInputNumber, {
            modelValue: p.value?.[axis],
            disabled: p.disabled,
            controlsPosition: 'right',
            placeholder: axis.toUpperCase(),
            'onUpdate:modelValue': value => out('change', { ...p.value, [axis]: value }),
          }),
        }),
      )),
    ])
  },
})

function hasPath(path) { let value = doc.value; for (const key of path.split('.').filter(Boolean)) { if (!value || !Object.prototype.hasOwnProperty.call(value, key)) return false; value = value[key] } return true }
function pickPath(paths, fallback) { return paths.find(hasPath) || fallback }
const timePath = computed(() => pickPath(['time', 'time_stepping'], 'time'))
const frequencyPath = computed(() => pickPath(['frequency', 'frequencies'], 'frequency'))
const solverPath = computed(() => pickPath(['solver'], 'solver'))
const materialsPath = computed(() => pickPath(['materials'], 'materials'))
const receiversPath = computed(() => pickPath(['receivers', 'receiver_points'], 'receivers'))
const segmentsPath = computed(() => pickPath(['source.segments', 'source.wire_segments', 'segments', 'wire_segments'], 'source.segments'))
const verticesPath = computed(() => pickPath(['source.vertices', 'source.loop_vertices', 'vertices', 'loop_vertices'], 'source.vertices'))
const frequencyKeys = computed(() => ({ count: hasPath(`${frequencyPath.value}.nfreq`) ? 'nfreq' : 'count', min: hasPath(`${frequencyPath.value}.fmin`) ? 'fmin' : (hasPath(`${frequencyPath.value}.min_hz`) ? 'min_hz' : 'minimum'), max: hasPath(`${frequencyPath.value}.fmax`) ? 'fmax' : (hasPath(`${frequencyPath.value}.max_hz`) ? 'max_hz' : 'maximum') }))
const solverKeys = computed(() => ({ mode: hasPath(`${solverPath.value}.solver_mode`) ? 'solver_mode' : 'mode', dimension: hasPath(`${solverPath.value}.rk_dimension`) ? 'rk_dimension' : 'dimension' }))
const materials = computed(() => getPath(materialsPath.value) || [])
const receivers = computed(() => getPath(receiversPath.value) || [])
const segments = computed(() => getPath(segmentsPath.value) || [])
const vertices = computed(() => getPath(verticesPath.value) || [])

function clone(value) { return JSON.parse(JSON.stringify(value)) }
function getPath(path, root = doc.value) { return path.split('.').filter(Boolean).reduce((value, key) => value?.[key], root) }
function get(path, key) { return getPath(`${path}.${key}`) }
function updatePath(path, value) { const next = clone(doc.value); const keys = path.split('.').filter(Boolean); let target = next; keys.slice(0, -1).forEach(key => { if (!target[key] || typeof target[key] !== 'object') target[key] = {}; target = target[key] }); target[keys.at(-1)] = value; emit('update:modelValue', next) }
function setField(path, key, value) { updatePath(`${path}.${key}`, value) }
function setArrayField(path, index, key, value) { const values = clone(getPath(path) || []); values[index][key] = value; updatePath(path, values) }
function setArrayItem(path, index, value) { const values = clone(getPath(path) || []); values[index] = value; updatePath(path, values) }
function appendArray(path, value) { updatePath(path, [...clone(getPath(path) || []), value]) }
function removeArrayItem(path, index) { const values = clone(getPath(path) || []); values.splice(index, 1); updatePath(path, values) }
function setAirIds(values) { updatePath('air_domain_ids', values.map(Number)) }
function addMaterial() { const ids = materials.value.map(item => Number(item.id) || 0); appendArray(materialsPath.value, { id: Math.max(0, ...ids) + 1, rho_x: 100, rho_y: 100, rho_z: 100, alpha: 0, beta: 0, gamma: 0, mu_r: 1, ...(isBe.value ? { epsilon_r: 1 } : {}) }) }
function copyMaterial(index) { const item = clone(materials.value[index]); item.id = Math.max(0, ...materials.value.map(value => Number(value.id) || 0)) + 1; appendArray(materialsPath.value, item) }
function removeMaterial(index) { removeArrayItem(materialsPath.value, index) }
function pointZero() { return { x: 0, y: 0, z: 0 } }
function segmentPointKey(segment, first) { const candidates = first ? ['start', 'a', 'p1'] : ['end', 'b', 'p2']; return candidates.find(key => Object.prototype.hasOwnProperty.call(segment || {}, key)) || candidates[0] }
function segmentPoint(segment, first) { return segment?.[segmentPointKey(segment, first)] || pointZero() }
function addSegment() { appendArray(segmentsPath.value, { start: pointZero(), end: pointZero() }) }
function setSegmentPoint(index, first, value) { setArrayField(segmentsPath.value, index, segmentPointKey(segments.value[index], first), value) }

function normalizePath(path) { return String(path || '$').replace(/^\$\.?/, '').replace(/\[(\d+)\]/g, '.$1').replace(/^document\./, '') }
function serverErrors() { const input = props.errors || []; if (Array.isArray(input)) return input.map(item => typeof item === 'string' ? { path: '$', message: item } : { path: normalizePath(item.path || item.loc), message: item.message || item.msg || String(item) }); return Object.entries(input).map(([path, message]) => ({ path: normalizePath(path), message: Array.isArray(message) ? message.join('；') : String(message) })) }
const errorList = computed(() => [...localErrors.value, ...serverErrors()])
function fieldError(path) { const normalized = normalizePath(path); return errorList.value.find(item => item.path === normalized)?.message || '' }
function pointError(path, axis) { return fieldError(`${path}.${axis}`) }
function finite(value) { return typeof value === 'number' && Number.isFinite(value) }
function validate() {
  const errors = []
  const add = (path, message) => errors.push({ path, message })
  if (isBe.value) {
    if (!Number.isInteger(get(timePath.value, 'blocks')) || get(timePath.value, 'blocks') <= 0) add(`${timePath.value}.blocks`, '必须是正整数')
    if (!Number.isInteger(get(timePath.value, 'steps_per_block')) || get(timePath.value, 'steps_per_block') <= 0) add(`${timePath.value}.steps_per_block`, '必须是正整数')
    if (!finite(get(timePath.value, 'base_time_step')) || get(timePath.value, 'base_time_step') <= 0) add(`${timePath.value}.base_time_step`, '必须大于 0')
  } else {
    const count = get(frequencyPath.value, frequencyKeys.value.count); const min = get(frequencyPath.value, frequencyKeys.value.min); const max = get(frequencyPath.value, frequencyKeys.value.max)
    if (!Number.isInteger(count) || count <= 0) add(`${frequencyPath.value}.${frequencyKeys.value.count}`, '必须是正整数')
    if (!finite(min) || min <= 0) add(`${frequencyPath.value}.${frequencyKeys.value.min}`, '必须大于 0')
    if (!finite(max) || max <= 0) add(`${frequencyPath.value}.${frequencyKeys.value.max}`, '必须大于 0')
    else if (count === 1 && finite(min) && max !== min) add(`${frequencyPath.value}.${frequencyKeys.value.max}`, '单频计算时必须等于最小频率')
    else if (count > 1 && finite(min) && max <= min) add(`${frequencyPath.value}.${frequencyKeys.value.max}`, '多频计算时必须大于最小频率')
    const mode = get(solverPath.value, solverKeys.value.mode); if (![1, 2].includes(mode)) add(`${solverPath.value}.${solverKeys.value.mode}`, '只能选择 1 或 2')
    const dimension = get(solverPath.value, solverKeys.value.dimension)
    if (!Number.isInteger(dimension) || dimension <= 0) add(`${solverPath.value}.${solverKeys.value.dimension}`, '必须是正整数')
    else if (mode === 2 && dimension < 2) add(`${solverPath.value}.${solverKeys.value.dimension}`, 'Rational Krylov 模式下至少为 2')
  }
  const ids = new Set(); materials.value.forEach((mat, index) => { if (!Number.isInteger(mat.id) || mat.id <= 0) add(`materials.${index}.id`, '必须是正整数'); else if (ids.has(mat.id)) add(`materials.${index}.id`, '材料 ID 不能重复'); else ids.add(mat.id); ['rho_x','rho_y','rho_z','mu_r', ...(isBe.value ? ['epsilon_r'] : [])].forEach(key => { if (!finite(mat[key]) || mat[key] <= 0) add(`materials.${index}.${key}`, '必须大于 0') }); ['alpha','beta','gamma'].forEach(key => { if (!finite(mat[key])) add(`materials.${index}.${key}`, '必须是有限数值') }) })
  if (!materials.value.length) add('materials', '至少需要一行材料')
  const airSeen = new Set(); (doc.value.air_domain_ids || []).forEach((id, index) => { if (!Number.isInteger(id) || id <= 0) add(`air_domain_ids.${index}`, '必须是正整数'); else if (airSeen.has(id)) add(`air_domain_ids.${index}`, '空气域 ID 不能重复'); else { airSeen.add(id); if (!ids.has(id)) add(`air_domain_ids.${index}`, '空气域 ID 必须在材料表中定义') } })
  if (!finite(doc.value.source?.current) || doc.value.source.current === 0) add('source.current', '电流不能为 0')
  const checkPoint = (point, path) => ['x','y','z'].forEach(axis => { if (!finite(point?.[axis])) add(`${path}.${axis}`, '必须是有限数值') })
  const samePoint = (left, right) => ['x','y','z'].every(axis => left?.[axis] === right?.[axis])
  if (isLoop.value) { if (!Number.isInteger(doc.value.source?.turns) || doc.value.source.turns <= 0) add('source.turns', '必须是正整数'); if (vertices.value.length < 3) add(verticesPath.value, '闭合回线至少需要 3 个顶点'); vertices.value.forEach((point, index) => { checkPoint(point, `${verticesPath.value}.${index}`); if (vertices.value.length > 1 && samePoint(point, vertices.value[(index + 1) % vertices.value.length])) add(`${verticesPath.value}.${(index + 1) % vertices.value.length}`, '相邻回线顶点不能重合') }) }
  else { if (!segments.value.length) add(segmentsPath.value, '至少需要一条导线线段'); segments.value.forEach((segment, index) => { const start = segmentPoint(segment, true); const end = segmentPoint(segment, false); checkPoint(start, `${segmentsPath.value}.${index}.${segmentPointKey(segment, true)}`); checkPoint(end, `${segmentsPath.value}.${index}.${segmentPointKey(segment, false)}`); if (samePoint(start, end)) add(`${segmentsPath.value}.${index}.${segmentPointKey(segment, false)}`, '线段两个端点不能重合') }) }
  if (!receivers.value.length) add(receiversPath.value, '至少需要一个接收点'); receivers.value.forEach((point, index) => checkPoint(point, `${receiversPath.value}.${index}`))
  localErrors.value = errors
  return errors.length === 0
}
watch(() => props.modelValue, () => { localErrors.value = [] })
defineExpose({ validate, errorList })
</script>

<style scoped>
.source-form { display:flex; flex-direction:column; gap:16px; }.error-summary ul { margin:8px 0 0; padding-left:20px; }.section-card { border-radius:8px; }.section-title { display:flex; flex-direction:column; gap:3px; font-weight:600; }.section-title small,.hint { color:#909399; font-size:12px; font-weight:400; }.section-head,.item-head,.geometry-title { display:flex; align-items:center; justify-content:space-between; gap:12px; }.section-head { margin:10px 0 12px; }.item-block,.geometry-row { margin-top:12px; padding:14px; border:1px solid #e4e7ed; border-radius:7px; background:#fafafa; }.item-head,.geometry-title { margin-bottom:10px; }.geometry-row { display:grid; grid-template-columns:120px minmax(0,1fr) minmax(0,1fr); align-items:start; }.geometry-row.compact { grid-template-columns:120px minmax(0,1fr); }.point-label { color:#606266; font-size:14px; margin-bottom:7px; }.point-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; }.point-grid :deep(.el-input-number) { width:100%; }.point-grid :deep(.el-form-item) { margin-bottom:8px; }.readonly :deep(.el-input-number.is-disabled .el-input__wrapper) { background:#f7f8fa; }
@media (max-width:760px) { .geometry-row,.geometry-row.compact { grid-template-columns:1fr; }.point-grid { grid-template-columns:1fr; } }
</style>
