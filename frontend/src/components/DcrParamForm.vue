<template>
  <div class="dcr-form" :class="{ readonly }">
    <el-alert v-if="errorList.length" type="error" :closable="false" class="error-summary">
      <template #title>发现 {{ errorList.length }} 处问题，请检查标红字段</template>
      <ul><li v-for="item in errorList.slice(0, 8)" :key="item.path">{{ item.path }}：{{ item.message }}</li></ul>
    </el-alert>

    <el-card shadow="never" class="section-card">
      <template #header><div class="section-title"><span>全局设置</span><small>计算边界与输出控制</small></div></template>
      <el-row :gutter="20">
        <el-col :xs="24" :sm="8">
          <el-form-item label="边界模式" :error="err('boundary_mode')">
            <el-select :model-value="doc.boundary_mode" :disabled="readonly" @update:model-value="setRoot('boundary_mode', $event)">
              <el-option label="1 — Robin 远场边界" :value="1" /><el-option label="2 — 零 Dirichlet 边界" :value="2" />
            </el-select>
            <div class="hint">可选值：1 或 2</div>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="8">
          <el-form-item label="写出 VTK">
            <el-switch :model-value="doc.write_vtk" :disabled="readonly" @update:model-value="setRoot('write_vtk', $event)" />
            <div class="hint">控制是否生成 VTK 可视化结果</div>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="8">
          <el-form-item label="空气域编号" :error="err('air_domain_ids')">
            <el-select :model-value="doc.air_domain_ids" multiple allow-create filterable default-first-option :disabled="readonly"
              placeholder="输入整数后回车" @update:model-value="setAirIds">
              <el-option v-for="id in doc.air_domain_ids" :key="id" :label="String(id)" :value="id" />
            </el-select>
            <div class="hint">整数列表；输入域 ID 后按回车</div>
          </el-form-item>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header><div class="section-head"><div class="section-title"><span>材料</span><small>各向异性电阻率与姿态角</small></div><el-button v-if="!readonly" type="primary" plain @click="addMaterial">新增材料</el-button></div></template>
      <el-empty v-if="!doc.materials.length" description="暂无材料" />
      <div v-for="(mat, mi) in doc.materials" :key="mat._key || mi" class="item-block">
        <div class="item-head"><strong>材料 {{ mi + 1 }}</strong><div v-if="!readonly"><el-button link type="primary" @click="copyMaterial(mi)">复制</el-button><el-button link type="danger" @click="removeMaterial(mi)">删除</el-button></div></div>
        <el-row :gutter="12">
          <el-col :xs="12" :sm="6" :md="3"><NumField label="ID" :value="mat.id" integer unit="域编号" :disabled="readonly" :error="err(`materials.${mi}.id`)" @change="setMaterial(mi, 'id', $event)" /></el-col>
          <el-col v-for="axis in ['x','y','z']" :key="axis" :xs="12" :sm="6" :md="3"><NumField :label="`ρ${axis}`" :value="mat[`rho_${axis}`]" unit="Ω·m" :disabled="readonly" :error="err(`materials.${mi}.rho_${axis}`)" @change="setMaterial(mi, `rho_${axis}`, $event)" /></el-col>
          <el-col v-for="angle in ['alpha','beta','gamma']" :key="angle" :xs="12" :sm="6" :md="4"><NumField :label="angleLabel(angle)" :value="mat[angle]" unit="°" :disabled="readonly" :error="err(`materials.${mi}.${angle}`)" @change="setMaterial(mi, angle, $event)" /></el-col>
        </el-row>
      </div>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header><div class="section-head"><div class="section-title"><span>电流源</span><small>A/B 电极与观测电极对</small></div><el-button v-if="!readonly" type="primary" plain @click="addSource">新增电流源</el-button></div></template>
      <el-empty v-if="!doc.sources.length" description="暂无电流源" />
      <div v-for="(source, si) in doc.sources" :key="source._key || si" class="source-block">
        <div class="item-head"><strong>电流源 {{ si + 1 }}</strong><div v-if="!readonly"><el-button link type="primary" @click="copySource(si)">复制</el-button><el-button link type="danger" @click="removeSource(si)">删除</el-button></div></div>
        <el-row :gutter="12">
          <el-col :xs="24" :sm="6"><NumField label="电流" :value="source.current" unit="A" :disabled="readonly" :error="err(`sources.${si}.current`)" @change="setSource(si, 'current', $event)" /></el-col>
          <el-col :xs="24" :sm="9"><VectorFields label="A 电极" :value="source.a" :disabled="readonly" :error-at="p => err(`sources.${si}.a.${p}`)" @change="setVector(si, 'a', $event)" /></el-col>
          <el-col :xs="24" :sm="9"><VectorFields label="B 电极" :value="source.b" :disabled="readonly" :error-at="p => err(`sources.${si}.b.${p}`)" @change="setVector(si, 'b', $event)" /></el-col>
        </el-row>
        <div class="sub-head"><span>观测电极对</span><el-button v-if="!readonly" size="small" @click="addObservation(si)">新增观测</el-button></div>
        <el-empty v-if="!source.observations.length" :image-size="48" description="暂无观测" />
        <div v-for="(obs, oi) in source.observations" :key="obs._key || oi" class="observation-row">
          <div class="observation-title"><span>观测 {{ oi + 1 }}</span><div v-if="!readonly"><el-button link type="primary" @click="copyObservation(si, oi)">复制</el-button><el-button link type="danger" @click="removeObservation(si, oi)">删除</el-button></div></div>
          <el-row :gutter="12">
            <el-col :xs="24" :md="8"><VectorFields label="M 电极" :value="obs.m" :disabled="readonly" :error-at="p => err(`sources.${si}.observations.${oi}.m.${p}`)" @change="setObservationVector(si, oi, 'm', $event)" /></el-col>
            <el-col :xs="24" :md="8"><VectorFields label="N 电极" :value="obs.n" :disabled="readonly" :error-at="p => err(`sources.${si}.observations.${oi}.n.${p}`)" @change="setObservationVector(si, oi, 'n', $event)" /></el-col>
            <el-col :xs="12" :md="4"><el-form-item label="几何模式" :error="err(`sources.${si}.observations.${oi}.geometry_mode`)"><el-select :model-value="obs.geometry_mode" :disabled="readonly" @update:model-value="setObservation(si, oi, 'geometry_mode', $event)"><el-option v-for="mode in [0,1,2,3]" :key="mode" :label="String(mode)" :value="mode" /></el-select><div class="hint">0–3</div></el-form-item></el-col>
            <el-col :xs="12" :md="4"><NumField label="自定义 K" :value="obs.custom_k" unit="m" :disabled="readonly" :error="err(`sources.${si}.observations.${oi}.custom_k`)" @change="setObservation(si, oi, 'custom_k', $event)" /></el-col>
          </el-row>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, reactive } from 'vue'
import { ElFormItem, ElInputNumber } from 'element-plus'

const props = defineProps({ modelValue: { type: Object, default: () => ({}) }, readonly: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue'])
const errors = reactive({})
const errorList = computed(() => Object.entries(errors).filter(([, message]) => message).map(([path, message]) => ({ path, message })))
const doc = computed(() => normalize(props.modelValue))

const NumField = defineComponent({
  props: { label: String, value: Number, unit: String, disabled: Boolean, integer: Boolean, error: String },
  emits: ['change'],
  setup(p, { emit: out }) {
    return () => h(ElFormItem, { label: p.label, error: p.error }, {
      default: () => [
        h(ElInputNumber, {
          modelValue: p.value,
          disabled: p.disabled,
          precision: p.integer ? 0 : undefined,
          step: p.integer ? 1 : 0.1,
          controlsPosition: 'right',
          style: 'width:100%',
          'onUpdate:modelValue': value => out('change', value),
        }),
        p.unit ? h('div', { class: 'hint' }, `单位：${p.unit}`) : null,
      ],
    })
  },
})
const VectorFields = defineComponent({
  props: { label: String, value: Object, disabled: Boolean, errorAt: Function },
  emits: ['change'],
  setup(p, { emit: out }) {
    return () => h('div', { class: 'vector' }, [
      h('div', { class: 'vector-label' }, `${p.label}（m）`),
      h('div', { class: 'vector-fields' }, ['x', 'y', 'z'].map(axis =>
        h(ElFormItem, { error: p.errorAt?.(axis), class: 'vector-item' }, {
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

function normalize(value = {}) { return { boundary_mode: value.boundary_mode, write_vtk: Boolean(value.write_vtk), air_domain_ids: Array.isArray(value.air_domain_ids) ? value.air_domain_ids : [], materials: Array.isArray(value.materials) ? value.materials : [], sources: Array.isArray(value.sources) ? value.sources.map(s => ({ ...s, a: s.a || {}, b: s.b || {}, observations: Array.isArray(s.observations) ? s.observations : [] })) : [] } }
function clone(v) { return JSON.parse(JSON.stringify(v)) }
function update(mutator) { const next = clone(doc.value); mutator(next); emit('update:modelValue', next) }
function clearPath(path) { delete errors[path] }
function setRoot(k, v) { clearPath(k); update(d => { d[k] = v }) }
function setAirIds(values) { const ids = values.map(v => typeof v === 'number' ? v : Number(String(v).trim())); clearPath('air_domain_ids'); update(d => { d.air_domain_ids = ids }) }
function setMaterial(i, k, v) { clearPath(`materials.${i}.${k}`); update(d => { d.materials[i][k] = v }) }
function setSource(i, k, v) { clearPath(`sources.${i}.${k}`); update(d => { d.sources[i][k] = v }) }
function setVector(i, k, v) { update(d => { d.sources[i][k] = v }); Object.keys(v).forEach(p => clearPath(`sources.${i}.${k}.${p}`)) }
function setObservation(si, oi, k, v) { clearPath(`sources.${si}.observations.${oi}.${k}`); update(d => { d.sources[si].observations[oi][k] = v }) }
function setObservationVector(si, oi, k, v) { update(d => { d.sources[si].observations[oi][k] = v }); Object.keys(v).forEach(p => clearPath(`sources.${si}.observations.${oi}.${k}.${p}`)) }
function materialTemplate() { return { id: null, rho_x: null, rho_y: null, rho_z: null, alpha: 0, beta: 0, gamma: 0 } }
function observationTemplate() { return { m: { x: null, y: null, z: null }, n: { x: null, y: null, z: null }, geometry_mode: 0, custom_k: 0 } }
function sourceTemplate() { return { current: null, a: { x: null, y: null, z: null }, b: { x: null, y: null, z: null }, observations: [] } }
function addMaterial() { update(d => d.materials.push(materialTemplate())) }
function copyMaterial(i) { update(d => d.materials.splice(i + 1, 0, clone(d.materials[i]))) }
function removeMaterial(i) { update(d => d.materials.splice(i, 1)) }
function addSource() { update(d => d.sources.push(sourceTemplate())) }
function copySource(i) { update(d => d.sources.splice(i + 1, 0, clone(d.sources[i]))) }
function removeSource(i) { update(d => d.sources.splice(i, 1)) }
function addObservation(si) { update(d => d.sources[si].observations.push(observationTemplate())) }
function copyObservation(si, oi) { update(d => d.sources[si].observations.splice(oi + 1, 0, clone(d.sources[si].observations[oi]))) }
function removeObservation(si, oi) { update(d => d.sources[si].observations.splice(oi, 1)) }
function angleLabel(v) { return ({ alpha: 'α', beta: 'β', gamma: 'γ' })[v] }
function err(path) { return errors[path] || '' }
function requiredNumber(path, value, label, integer = false) { if (typeof value !== 'number' || !Number.isFinite(value)) errors[path] = `${label}必须是有效数字`; else if (integer && !Number.isInteger(value)) errors[path] = `${label}必须是整数` }
function validate() {
  Object.keys(errors).forEach(k => delete errors[k]); const d = doc.value
  if (![1, 2].includes(d.boundary_mode)) errors.boundary_mode = '边界模式必须为 1 或 2'
  if (!Array.isArray(d.air_domain_ids) || d.air_domain_ids.some(v => !Number.isInteger(v))) errors.air_domain_ids = '空气域编号必须全部为整数'
  d.materials.forEach((m, i) => { requiredNumber(`materials.${i}.id`, m.id, '材料 ID', true); ['rho_x','rho_y','rho_z','alpha','beta','gamma'].forEach(k => requiredNumber(`materials.${i}.${k}`, m[k], k)) })
  d.sources.forEach((s, si) => { requiredNumber(`sources.${si}.current`, s.current, '电流'); ['a','b'].forEach(v => ['x','y','z'].forEach(k => requiredNumber(`sources.${si}.${v}.${k}`, s[v]?.[k], `${v.toUpperCase()}.${k}`))); s.observations.forEach((o, oi) => { ['m','n'].forEach(v => ['x','y','z'].forEach(k => requiredNumber(`sources.${si}.observations.${oi}.${v}.${k}`, o[v]?.[k], `${v.toUpperCase()}.${k}`))); if (![0,1,2,3].includes(o.geometry_mode)) errors[`sources.${si}.observations.${oi}.geometry_mode`] = '几何模式必须为 0–3'; requiredNumber(`sources.${si}.observations.${oi}.custom_k`, o.custom_k, '自定义 K') }) })
  return errorList.value.length === 0
}
function normalizeErrorPath(path) { return String(path).replace(/^\$\.?/, '').replace(/^document\./, '').replace(/\[(\d+)\]/g, '.$1') || 'document' }
function setServerErrors(input) { Object.keys(errors).forEach(k => delete errors[k]); if (!input) return; if (Array.isArray(input)) input.forEach(item => { const path = Array.isArray(item.loc) ? item.loc.filter(v => v !== 'body' && v !== 'document').join('.') : (item.path || 'document'); errors[normalizeErrorPath(path)] = item.msg || item.message || '值无效' }); else Object.entries(input).forEach(([path, message]) => { errors[normalizeErrorPath(path)] = Array.isArray(message) ? message.join('；') : String(message) }) }
function collectErrors() { return errorList.value.map(item => ({ ...item })) }
defineExpose({ validate, collectErrors, setServerErrors })
</script>

<style scoped>
.dcr-form { width: 100%; }.error-summary,.section-card { margin-bottom: 18px; }.error-summary ul { margin: 8px 0 0; padding-left: 20px; }.section-head,.item-head,.sub-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }.section-title { display:flex; flex-direction:column; gap:3px; font-weight:600; }.section-title small { color:#909399; font-weight:400; }.item-block,.source-block { border:1px solid #dcdfe6; border-radius:8px; padding:16px; margin-bottom:14px; }.source-block { background:#fafafa; }.item-head { margin-bottom:12px; }.sub-head { margin:10px 0; padding-top:12px; border-top:1px dashed #dcdfe6; font-weight:600; }.observation-row { background:#fff; border:1px solid #ebeef5; border-radius:6px; padding:12px; margin-top:10px; }.observation-title { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; color:#606266; }.hint { width:100%; margin-top:3px; color:#909399; font-size:12px; line-height:1.3; }.vector-label { margin-bottom:8px; color:#606266; font-size:14px; }.vector-fields { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; }.vector-item { margin-bottom:12px; }.vector :deep(.el-input-number) { width:100%; }.readonly :deep(.el-input-number.is-disabled .el-input__wrapper),.readonly :deep(.el-input.is-disabled .el-input__wrapper) { background:#f7f8fa; }
@media (max-width: 640px) { .vector-fields { grid-template-columns:1fr; }.section-head { align-items:flex-start; } }
</style>
