# 实体百科局部主题整理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为实体百科页面建立局部主题层，统一目录标签、人工覆盖区、详情表格和分类依据卡的深色配色语言，不扩展为全站换肤。

**Architecture:** 在 `Entities.vue` 根节点增加局部主题作用域类，使用 `--entities-*` 语义变量集中定义配色，再由 `EntityTree.vue`、`EntityGroupTable.vue`、`EntityDetailPanel.vue` 只消费这些变量。测试以现有组件测试为基础，先补充 class/token 断言，再完成样式实现，最后跑定向 Vitest 验证不回归。

**Tech Stack:** Vue 3 `script setup`、Element Plus、Tailwind utility classes、scoped CSS、Vitest、Vue Test Utils

---

### Task 1: 建立局部主题作用域与测试入口

**Files:**
- Modify: `src/novel_dev/web/src/views/Entities.vue`
- Modify: `src/novel_dev/web/src/views/Entities.test.js`
- Test: `src/novel_dev/web/src/views/Entities.test.js`

- [ ] **Step 1: 写一个会失败的视图测试，锁定局部主题作用域类**

在 `src/novel_dev/web/src/views/Entities.test.js` 里新增一个断言，要求页面根节点包含局部主题 class，避免后续样式变量没有稳定挂载点。

```js
it('adds the local entities theme scope on the page root', () => {
  seedStore()
  const wrapper = mountView()

  expect(wrapper.find('.entities-page').exists()).toBe(true)
  expect(wrapper.find('.entities-page').classes()).toContain('entities-theme')
})
```

- [ ] **Step 2: 运行该测试并确认失败**

Run: `pnpm vitest run src/novel_dev/web/src/views/Entities.test.js -t "adds the local entities theme scope on the page root"`

Expected: FAIL，提示找不到 `.entities-page` 或缺少 `entities-theme`。

- [ ] **Step 3: 在 `Entities.vue` 增加局部主题根节点**

把当前模板最外层容器从：

```vue
<div class="space-y-4">
```

改成：

```vue
<div class="entities-page entities-theme space-y-4">
```

如果后续需要更细粒度约束，可在该根节点下继续挂 `data-page="entities"`，但本次先不要扩 scope。

- [ ] **Step 4: 重新运行测试并确认通过**

Run: `pnpm vitest run src/novel_dev/web/src/views/Entities.test.js -t "adds the local entities theme scope on the page root"`

Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add src/novel_dev/web/src/views/Entities.vue src/novel_dev/web/src/views/Entities.test.js
git commit -m "test: add local entities theme scope"
```

### Task 2: 定义局部主题 token 并挂到实体百科页面

**Files:**
- Modify: `src/novel_dev/web/src/style.css`
- Modify: `src/novel_dev/web/src/views/Entities.vue`
- Test: `src/novel_dev/web/src/views/Entities.test.js`

- [ ] **Step 1: 为 token 容器增加一个失败断言**

在 `src/novel_dev/web/src/views/Entities.test.js` 再补一个轻量断言，要求主题根节点存在用于样式消费的 `entities-theme` class，不直接测颜色值，只锁定结构。

```js
it('keeps the entities theme scope on the workspace root', () => {
  seedStore()
  const wrapper = mountView()

  const page = wrapper.find('.entities-theme')
  expect(page.exists()).toBe(true)
  expect(page.find('.entity-tree-stub').exists()).toBe(true)
})
```

- [ ] **Step 2: 在全局样式中写入实体百科局部变量**

在 `src/novel_dev/web/src/style.css` 添加一段局部主题变量，放在现有通用 surface 样式之后，避免被更早规则覆盖。

```css
.entities-theme {
  --entities-panel-bg: rgba(11, 20, 35, 0.82);
  --entities-panel-bg-soft: rgba(18, 30, 49, 0.88);
  --entities-panel-bg-muted: rgba(29, 42, 63, 0.92);
  --entities-panel-border: rgba(134, 154, 184, 0.18);
  --entities-panel-border-strong: rgba(148, 172, 208, 0.28);
  --entities-text: #e7eefc;
  --entities-text-muted: #b5c1d8;
  --entities-text-soft: #8f9db7;
  --entities-accent: #58a6ff;
  --entities-accent-soft: rgba(88, 166, 255, 0.14);
  --entities-warning: #f2b66d;
  --entities-warning-soft: rgba(242, 182, 109, 0.16);
  --entities-danger: #f28b82;
  --entities-chip-bg: rgba(227, 232, 242, 0.08);
  --entities-chip-border: rgba(185, 196, 214, 0.16);
  --entities-grid-label-bg: rgba(108, 123, 149, 0.34);
  --entities-grid-content-bg: rgba(231, 236, 245, 0.08);
  --entities-info-bg: rgba(243, 247, 255, 0.06);
}
```

- [ ] **Step 3: 保持 `Entities.vue` 只负责作用域，不在页面内写死颜色**

不要在 `Entities.vue` 新增零散的内联 style。页面文件只保留：

```vue
<div class="entities-page entities-theme space-y-4">
```

样式集中在 `style.css` 和各组件自身 scoped CSS。

- [ ] **Step 4: 运行视图测试确认作用域没有被破坏**

Run: `pnpm vitest run src/novel_dev/web/src/views/Entities.test.js`

Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add src/novel_dev/web/src/style.css src/novel_dev/web/src/views/Entities.vue src/novel_dev/web/src/views/Entities.test.js
git commit -m "style: add local entities theme tokens"
```

### Task 3: 整理目录标签与搜索区样式

**Files:**
- Modify: `src/novel_dev/web/src/components/entities/EntityTree.vue`
- Modify: `src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`
- Test: `src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`

- [ ] **Step 1: 先写失败测试，要求目录标签具备可主题化 class**

在 `src/novel_dev/web/src/components/entities/EntitiesTheme.test.js` 中给 `EntityTree` 增加断言，锁定标签和搜索区的 class 名，而不是直接测颜色。

```js
it('renders themeable badge classes in the entity tree', () => {
  const wrapper = mount(EntityTree, {
    props: {
      nodes: [{
        id: 'category:1',
        label: '人物',
        nodeType: 'category',
        entityCount: 2,
        needsReviewCount: 1,
      }],
      totalCount: 2,
      treeNodeCount: 1,
    },
    global: {
      stubs: simpleStubs,
      directives: { loading: () => {} },
    },
  })

  expect(wrapper.find('.entity-tree__badge').exists()).toBe(true)
  expect(wrapper.find('.entity-tree__badge--warning').exists()).toBe(true)
  expect(wrapper.find('.entity-tree__search').exists()).toBe(true)
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pnpm vitest run src/novel_dev/web/src/components/entities/EntitiesTheme.test.js -t "renders themeable badge classes in the entity tree"`

Expected: FAIL，提示找不到新增 class。

- [ ] **Step 3: 在 `EntityTree.vue` 中为标签和搜索区加 class，并切换到局部 token**

把模板中的标签区域改成显式 class：

```vue
<el-input
  class="entity-tree__search"
  :model-value="searchQuery"
  clearable
  placeholder="搜索实体、别名、关系"
  @update:model-value="emit('update:searchQuery', $event)"
  @keyup.enter="emit('search')"
  @clear="emit('reset')"
>
```

```vue
<div class="flex shrink-0 flex-wrap items-center justify-end gap-1 max-w-[7.5rem]">
  <el-tag
    v-if="nodeBadge(data)"
    class="entity-tree__badge"
    size="small"
    type="info"
  >
    {{ nodeBadge(data) }}
  </el-tag>
  <el-tag
    v-if="nodeHint(data)"
    class="entity-tree__badge entity-tree__badge--warning"
    size="small"
    type="warning"
  >
    {{ nodeHint(data) }}
  </el-tag>
</div>
```

同时把 scoped CSS 从 `--app-*` 切到 `--entities-*`：

```css
.entity-tree {
  background: var(--entities-panel-bg);
  border-color: var(--entities-panel-border);
}

.entity-tree :deep(.el-input__wrapper) {
  background: var(--entities-panel-bg-soft);
  box-shadow: 0 0 0 1px var(--entities-panel-border) inset;
}

.entity-tree :deep(.el-input-group__append) {
  background: var(--entities-panel-bg-muted);
  color: var(--entities-text);
}

.entity-tree :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: color-mix(in srgb, var(--entities-accent) 14%, var(--entities-panel-bg-soft));
}

.entity-tree :deep(.el-tag.entity-tree__badge) {
  background: var(--entities-chip-bg);
  border-color: var(--entities-chip-border);
  color: var(--entities-text-muted);
}

.entity-tree :deep(.el-tag.entity-tree__badge--warning) {
  background: var(--entities-warning-soft);
  border-color: color-mix(in srgb, var(--entities-warning) 55%, transparent);
  color: var(--entities-warning);
}
```

- [ ] **Step 4: 运行组件测试确认目录结构和 class 保持正确**

Run: `pnpm vitest run src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`

Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add src/novel_dev/web/src/components/entities/EntityTree.vue src/novel_dev/web/src/components/entities/EntitiesTheme.test.js
git commit -m "style: theme entities tree badges"
```

### Task 4: 整理分组表格与快速调整区样式

**Files:**
- Modify: `src/novel_dev/web/src/components/entities/EntityGroupTable.vue`
- Modify: `src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`
- Test: `src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`

- [ ] **Step 1: 写失败测试，锁定表格和快速调整区 class**

在 `EntitiesTheme.test.js` 为 `EntityGroupTable` 增加断言：

```js
it('renders themeable classes for the entity group table controls', () => {
  const wrapper = mount(EntityGroupTable, {
    props: {
      items: [{
        entity_id: 'e1',
        name: '陆照',
        classification_status: 'needs_review',
        system_category: '人物',
        system_group_name: '主角阵营',
        latest_state: {},
      }],
    },
    global: { stubs: simpleStubs },
  })

  expect(wrapper.find('.entity-group-table__table').exists()).toBe(true)
  expect(wrapper.find('.entity-group-table__quick-actions').exists()).toBe(true)
  expect(wrapper.find('.entity-group-table__select').exists()).toBe(true)
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pnpm vitest run src/novel_dev/web/src/components/entities/EntitiesTheme.test.js -t "renders themeable classes for the entity group table controls"`

Expected: FAIL

- [ ] **Step 3: 在 `EntityGroupTable.vue` 中加入表单 class，并用 `--entities-*` 重写表格层级**

模板改成：

```vue
<el-table v-else :data="items" class="entity-group-table__table" style="width: 100%" @row-click="emit('select-entity', $event)">
```

```vue
<el-select
  class="entity-group-table__select"
  v-model="draftFor(row).manualCategory"
  placeholder="选择一级分类"
  clearable
  style="width: 100%"
  @change="handleCategoryChange(row)"
>
```

```vue
<div class="entity-group-table__quick-actions flex flex-wrap gap-2">
  <el-button size="small" type="primary" @click="saveDraft(row)">保存</el-button>
  <el-button size="small" @click="emit('clear-override', row)">清除覆盖</el-button>
  <el-button size="small" link type="primary" @click="emit('select-entity', row)">详情</el-button>
</div>
```

样式重点替换：

```css
.entity-group-table {
  background: var(--entities-panel-bg);
  border-color: var(--entities-panel-border);
}

.entity-group-table__table {
  --el-table-border-color: var(--entities-panel-border);
  --el-table-header-bg-color: var(--entities-panel-bg-muted);
  --el-table-row-hover-bg-color: var(--entities-panel-bg-soft);
  --el-table-text-color: var(--entities-text);
  --el-table-header-text-color: var(--entities-text-soft);
}

.entity-group-table__table :deep(th.el-table__cell) {
  background: var(--entities-panel-bg-muted);
}

.entity-group-table__table :deep(td.el-table__cell) {
  background: var(--entities-panel-bg);
}

.entity-group-table :deep(.el-select__wrapper) {
  background: var(--entities-panel-bg-soft);
  box-shadow: 0 0 0 1px var(--entities-panel-border) inset;
}
```

- [ ] **Step 4: 运行组件测试确认通过**

Run: `pnpm vitest run src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`

Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add src/novel_dev/web/src/components/entities/EntityGroupTable.vue src/novel_dev/web/src/components/entities/EntitiesTheme.test.js
git commit -m "style: theme entities group table"
```

### Task 5: 整理详情面板、人工覆盖区和分类依据卡

**Files:**
- Modify: `src/novel_dev/web/src/components/entities/EntityDetailPanel.vue`
- Modify: `src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`
- Test: `src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`

- [ ] **Step 1: 写失败测试，锁定人工覆盖区和依据卡的主题 class**

在 `EntitiesTheme.test.js` 增加：

```js
it('renders themeable classes for the detail panel sections', () => {
  const wrapper = mount(EntityDetailPanel, {
    props: {
      title: '实体详情',
      entity: {
        entity_id: 'e1',
        name: '陆照',
        type: 'character',
        classification_status: 'manual_override',
        classification_reason: { reason: 'entity_type_match' },
        latest_state: { identity: '主角' },
      },
      relationships: [],
    },
    global: { stubs: simpleStubs },
  })

  expect(wrapper.find('.entity-detail-panel__override').exists()).toBe(true)
  expect(wrapper.find('.entity-detail-panel__reason').exists()).toBe(true)
  expect(wrapper.find('.entity-detail-panel__descriptions').exists()).toBe(true)
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pnpm vitest run src/novel_dev/web/src/components/entities/EntitiesTheme.test.js -t "renders themeable classes for the detail panel sections"`

Expected: FAIL

- [ ] **Step 3: 在 `EntityDetailPanel.vue` 中加入显式 class，并切换到局部 token**

模板调整：

```vue
<div class="entity-detail-panel__section entity-detail-panel__override rounded-lg border p-3 space-y-3">
```

```vue
<el-alert
  v-if="entity.classification_reason"
  class="entity-detail-panel__reason"
  title="分类依据"
  type="info"
  show-icon
  :closable="false"
>
```

将 scoped CSS 主要替换为：

```css
.entity-detail-panel {
  background: var(--entities-panel-bg);
  border-color: var(--entities-panel-border);
}

.entity-detail-panel__section {
  border-color: var(--entities-panel-border);
  background: var(--entities-panel-bg-soft);
}

.entity-detail-panel__descriptions {
  --el-descriptions-table-border: 1px solid var(--entities-panel-border);
  --el-descriptions-item-bordered-label-background: var(--entities-grid-label-bg);
  --el-descriptions-item-bordered-content-background: var(--entities-grid-content-bg);
  --el-text-color-regular: var(--entities-text);
  --el-text-color-primary: var(--entities-text);
}

.entity-detail-panel__reason :deep(.el-alert) {
  background: var(--entities-info-bg);
  border: 1px solid var(--entities-panel-border);
}

.entity-detail-panel :deep(.el-select__wrapper),
.entity-detail-panel :deep(.el-input__wrapper) {
  background: var(--entities-panel-bg-muted);
  box-shadow: 0 0 0 1px var(--entities-panel-border) inset;
}
```

按钮语义保持：

- `保存覆盖` 是唯一 `type="primary"` 主动作
- `清除覆盖` 和 `重新判断` 保持中性按钮
- 删除实体继续保留危险语义，但不纳入本次主要配色调整

- [ ] **Step 4: 运行组件测试确认通过**

Run: `pnpm vitest run src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`

Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add src/novel_dev/web/src/components/entities/EntityDetailPanel.vue src/novel_dev/web/src/components/entities/EntitiesTheme.test.js
git commit -m "style: theme entities detail panel"
```

### Task 6: 做定向回归验证并准备人工验收

**Files:**
- Verify: `src/novel_dev/web/src/views/Entities.test.js`
- Verify: `src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`
- Verify: `src/novel_dev/web/src/components/entities/EntityTree.test.js`

- [ ] **Step 1: 运行实体百科视图测试**

Run: `pnpm vitest run src/novel_dev/web/src/views/Entities.test.js`

Expected: PASS

- [ ] **Step 2: 运行局部主题组件测试**

Run: `pnpm vitest run src/novel_dev/web/src/components/entities/EntitiesTheme.test.js`

Expected: PASS

- [ ] **Step 3: 运行目录树现有行为测试，确认样式改动没有影响交互**

Run: `pnpm vitest run src/novel_dev/web/src/components/entities/EntityTree.test.js`

Expected: PASS

- [ ] **Step 4: 本地人工检查实体百科页面**

Run: `pnpm dev`

人工检查：

- 左侧数量标签不再是突兀亮白胶囊
- `待确认` 标签是低饱和暖色，不刺眼
- 人工覆盖输入框不再是纯白块
- 描述表格标签列和内容列都属于同一深色体系
- “分类依据”卡不再是亮白信息框

- [ ] **Step 5: 提交最终验证结果**

```bash
git add src/novel_dev/web/src/views/Entities.vue src/novel_dev/web/src/style.css src/novel_dev/web/src/components/entities/EntityTree.vue src/novel_dev/web/src/components/entities/EntityGroupTable.vue src/novel_dev/web/src/components/entities/EntityDetailPanel.vue src/novel_dev/web/src/views/Entities.test.js src/novel_dev/web/src/components/entities/EntitiesTheme.test.js
git commit -m "style: unify entities workspace theme"
```

## Self-Review

### Spec coverage

- 局部主题作用域：Task 1, Task 2
- `--entities-*` 语义变量：Task 2
- 目录标签与待确认标签：Task 3
- 人工覆盖区：Task 5
- 详情表格：Task 5
- 分类依据卡：Task 5
- Element Plus 局部覆盖检查：Task 3, Task 4, Task 5
- 定向测试与人工验收：Task 6

未发现 spec 漏项。

### Placeholder scan

已检查计划中的步骤、命令、文件路径和代码片段，没有使用 `TODO`、`TBD`、`similar to` 之类占位描述。

### Type consistency

- 主题作用域统一使用 `entities-theme`
- 页面根节点统一使用 `entities-page`
- token 前缀统一使用 `--entities-*`
- 新增 class 名统一采用组件前缀：`entity-tree__*`、`entity-group-table__*`、`entity-detail-panel__*`

未发现命名冲突。
