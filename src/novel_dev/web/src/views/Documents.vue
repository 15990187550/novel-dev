<template>
  <div class="space-y-6">
    <section class="page-header">
      <div>
        <div class="page-header__eyebrow">Knowledge Base</div>
        <h1 class="page-header__title">设定与文风</h1>
        <p class="page-header__description">
          把导入、审核、已生效资料和文风版本收敛到同一个面板里，避免上下文分散。
        </p>
      </div>
      <div class="page-header__meta-grid">
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">待审核</span>
          <span class="page-header__meta-value">{{ pendingReviewCount }}</span>
        </div>
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">已生效资料</span>
          <span class="page-header__meta-value">{{ libraryItems.length }}</span>
        </div>
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">文风版本</span>
          <span class="page-header__meta-value">{{ styleProfiles.length }}</span>
        </div>
        <div class="page-header__meta-card">
          <span class="page-header__meta-label">当前版本</span>
          <span class="page-header__meta-value">{{ activeStyleVersionText }}</span>
        </div>
      </div>
    </section>

    <el-alert v-if="!store.novelId" title="请先选择或新建小说" type="info" show-icon />
    <template v-else>
      <div class="documents-tabs" role="tablist" aria-label="设定与文风工作区">
        <button
          type="button"
          class="documents-tab"
          :class="{ 'documents-tab--active': activeKnowledgeTab === 'import' }"
          role="tab"
          :aria-selected="activeKnowledgeTab === 'import'"
          data-testid="documents-tab-import"
          @click="selectKnowledgeTab('import')"
        >
          导入设定 / 文风
        </button>
        <button
          type="button"
          class="documents-tab"
          :class="{ 'documents-tab--active': activeKnowledgeTab === 'ai' }"
          role="tab"
          :aria-selected="activeKnowledgeTab === 'ai'"
          data-testid="documents-tab-ai"
          @click="selectKnowledgeTab('ai')"
        >
          AI 生成设定
        </button>
      </div>

      <div v-if="activeKnowledgeTab === 'import'" class="surface-card p-5">
        <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h3 class="font-bold">导入设定 / 文风样本</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              支持批量上传 `.txt` / `.md`。系统会自动识别是“设定文档”还是“文风样本”。
            </p>
          </div>
          <div class="rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/30 dark:text-blue-300">
            每个文件尽量只放一种内容，识别和审核会更稳定
          </div>
        </div>

        <div class="mt-4 grid gap-3 md:grid-cols-3 text-sm">
          <div class="rounded-xl border border-gray-200 dark:border-gray-700 p-3">
            <div class="font-semibold">支持文件</div>
            <div class="mt-2 text-gray-600 dark:text-gray-300">`.txt`、`.md`，可一次上传多个文件。</div>
          </div>
          <div class="rounded-xl border border-gray-200 dark:border-gray-700 p-3">
            <div class="font-semibold">设定文档会提取</div>
            <div class="mt-2 text-gray-600 dark:text-gray-300">世界观、修炼体系、势力格局、剧情梗概，以及人物/物品实体。</div>
          </div>
          <div class="rounded-xl border border-gray-200 dark:border-gray-700 p-3">
            <div class="font-semibold">文风样本会提取</div>
            <div class="mt-2 text-gray-600 dark:text-gray-300">文笔文风、叙事视角、节奏、写作规则、风格边界。</div>
          </div>
        </div>

        <div class="mt-4 rounded-2xl border border-gray-200 bg-gray-50/80 p-4 dark:border-gray-700 dark:bg-gray-900/50">
          <div class="text-sm font-semibold text-gray-900 dark:text-gray-100">资料用途</div>
          <div class="mt-3 grid gap-3 md:grid-cols-2">
            <button
              type="button"
              class="documents-import-mode"
              :class="{ 'documents-import-mode--active': knowledgeUsage === 'auto' }"
              @click="knowledgeUsage = 'auto'"
            >
              <span class="documents-import-mode__title">全局生效资料</span>
              <span class="documents-import-mode__desc">适合本书核心设定、主角、金手指、总体世界观、文风样本；批准后默认参与全书生成。</span>
            </button>
            <button
              type="button"
              class="documents-import-mode"
              :class="{ 'documents-import-mode--active': knowledgeUsage === 'domain' }"
              @click="knowledgeUsage = 'domain'"
            >
              <span class="documents-import-mode__title">局部生效规则域</span>
              <span class="documents-import-mode__desc">适合某个原著、世界、地图、阶段或修炼体系；先未绑定入库，后续按卷/章节动态激活。</span>
            </button>
          </div>
          <div v-if="knowledgeUsage === 'domain'" class="mt-3 max-w-xl">
            <label class="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              局部规则域名称
            </label>
            <el-input
              v-model="domainName"
              size="small"
              placeholder="例如：东荒规则域 / 上古遗迹 / 北境战线"
            />
            <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
              不需要指定第几卷，系统会在总纲生成后建议绑定范围。
            </p>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-2">
          <input ref="fileInput" type="file" accept=".txt,.md,text/plain,text/markdown" multiple @change="onFileChange" class="text-sm" />
          <el-button type="primary" :loading="uploading" @click="upload">上传</el-button>
        </div>

        <div v-if="selectedFiles.length" class="mt-3 rounded-xl bg-gray-50 dark:bg-gray-900/60 p-3 text-sm text-gray-600 dark:text-gray-300">
          <div class="font-medium text-gray-900 dark:text-gray-100">待导入文件</div>
          <div class="mt-2 flex flex-wrap gap-2">
            <span
              v-for="file in selectedFiles"
              :key="file.filename"
              class="rounded-full border border-gray-200 dark:border-gray-700 px-3 py-1"
            >
              {{ file.filename }}
            </span>
          </div>
        </div>

        <div v-if="uploadSummary" class="mt-3 space-y-2 text-sm">
          <div class="text-gray-700 dark:text-gray-300">
            本次导入任务已提交：已创建 {{ uploadSummary.accepted ?? uploadSummary.succeeded ?? 0 }} 条记录，失败 {{ uploadSummary.failed }}，共 {{ uploadSummary.total }} 个文件
          </div>
          <div v-if="uploadSummary.failed" class="text-red-600 dark:text-red-400 space-y-1">
            <div
              v-for="item in uploadSummary.items.filter(item => item.error)"
              :key="item.filename"
              class="whitespace-pre-wrap"
            >
              {{ item.filename }}：{{ item.error }}
            </div>
          </div>
        </div>
      </div>

      <SettingWorkbench v-else embedded />

      <section class="documents-management">
        <div class="documents-management__header">
          <div>
            <h2 class="documents-management__title">资料管理</h2>
            <p class="documents-management__description">
              已生效资料、局部规则域和审核记录集中在同一区域查看，避免在导入和 AI 生成流程之间来回跳转。
            </p>
          </div>
          <div class="documents-management__stats">
            <span>资料 {{ libraryItems.length }}</span>
            <span>规则域 {{ knowledgeDomains.length }}</span>
            <span>待处理 {{ pendingReviewCount }}</span>
          </div>
        </div>

        <div class="documents-management-grid">
      <div class="surface-card documents-panel documents-panel--library p-5">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h3 class="font-bold">当前资料库</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              已批准的设定和文风会沉淀在这里，供后续脑暴、卷纲和正文生成使用。
            </p>
          </div>
          <div class="text-sm text-gray-500 dark:text-gray-400">
            已生效 {{ libraryItems.length }} 份
          </div>
        </div>

        <div v-if="libraryLoading" class="mt-4 text-sm text-gray-500 dark:text-gray-400">加载资料库中...</div>
        <el-empty v-else-if="!hasLibraryContent" description="批准导入后，会在这里看到世界观、体系设定、剧情梗概和文风档案" />

        <div v-else class="mt-4 space-y-6">
          <section v-for="group in libraryGroups" :key="group.docType" class="space-y-3">
            <div class="flex items-center justify-between">
              <div class="font-semibold text-gray-900 dark:text-gray-100">{{ group.label }}</div>
              <div class="text-xs text-gray-500 dark:text-gray-400">{{ group.items.length }} 份</div>
            </div>
            <div class="space-y-3">
              <article
                v-for="item in group.items"
                :key="item.id"
                class="documents-library-card rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/70 dark:bg-gray-900/50 p-4"
              >
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="font-medium text-gray-900 dark:text-gray-100">
                      {{ item.title || group.label }}
                      <button
                        v-if="item.source_type === 'ai' && item.source_session_id"
                        type="button"
                        class="documents-ai-badge"
                        @click="openSourceSession(item.source_session_id, item.source_review_change_id)"
                      >
                        AI
                      </button>
                    </div>
                    <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      v{{ item.version || 1 }} · {{ formatTimestamp(item.updated_at) }}
                    </div>
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      type="button"
                      class="documents-library-card__edit"
                      @click="openLibraryDetail(item, group.label)"
                    >
                      查看详情
                    </button>
                    <button
                      type="button"
                      class="documents-library-card__edit"
                      title="编辑资料"
                      aria-label="编辑资料"
                      @click="openLibraryEditor(item, group.label)"
                    >
                      编辑
                    </button>
                  </div>
                </div>
                <p class="mt-3 line-clamp-3 whitespace-pre-wrap text-sm leading-6 text-gray-700 dark:text-gray-200">
                  {{ summarizeContent(item.content) }}
                </p>
              </article>
            </div>
          </section>

          <section v-if="styleProfiles.length" class="space-y-3">
            <div class="flex items-center justify-between">
              <div class="font-semibold text-gray-900 dark:text-gray-100">文风档案</div>
              <div class="flex items-center gap-2">
                <div class="text-xs text-gray-500 dark:text-gray-400">
                  当前生效版本：{{ activeStyleVersionText }}
                </div>
                <button
                  type="button"
                  class="documents-library-card__edit"
                  @click="openStyleVersions"
                >
                  查看更多版本
                </button>
              </div>
            </div>
            <div class="space-y-3">
              <div
                v-if="activeStyleProfile"
                :key="activeStyleProfile.id"
                class="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/70 dark:bg-gray-900/50 p-4"
              >
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div class="flex items-center gap-2">
                    <div class="font-medium text-gray-900 dark:text-gray-100">当前文风版本 v{{ activeStyleProfile.version }}</div>
                    <el-tag size="small" type="success">当前生效</el-tag>
                  </div>
                  <div class="flex items-center gap-2">
                    <div class="text-xs text-gray-500 dark:text-gray-400">{{ formatTimestamp(activeStyleProfile.updated_at) }}</div>
                    <button
                      type="button"
                      class="documents-library-card__edit"
                      title="编辑资料"
                      aria-label="编辑资料"
                      @click="openLibraryEditor(activeStyleProfile, '文风档案')"
                    >
                      编辑
                    </button>
                  </div>
                </div>

                <div class="mt-3 rounded-xl bg-white dark:bg-gray-800 p-3 border border-gray-200 dark:border-gray-700">
                  <div class="text-xs uppercase tracking-wide text-gray-400">Style Guide</div>
                  <div class="mt-2 line-clamp-4 whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-200">{{ activeStyleProfile.content }}</div>
                </div>

                <div v-if="styleSummaryItems(activeStyleProfile).length" class="mt-3 grid gap-3 md:grid-cols-3 text-sm">
                  <div
                    v-for="item in styleSummaryItems(activeStyleProfile)"
                    :key="item.label"
                    class="rounded-xl border border-gray-200 dark:border-gray-700 p-3"
                  >
                    <div class="text-xs text-gray-400">{{ item.label }}</div>
                    <div class="mt-1 whitespace-pre-wrap text-gray-700 dark:text-gray-200">{{ item.value }}</div>
                  </div>
                </div>

                <div class="mt-3 flex justify-end">
                  <button type="button" class="documents-library-card__edit" @click="openLibraryDetail(activeStyleProfile, '文风档案')">
                    查看完整文风
                  </button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>

      <div class="surface-card documents-panel documents-panel--domains p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 class="font-bold">规则域</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              原著、世界、体系资料默认不全局生效；生成卷纲时会按关键词和绑定范围动态激活。
            </p>
          </div>
          <el-button size="small" :loading="knowledgeDomainsLoading" @click="fetchKnowledgeDomains">刷新</el-button>
        </div>

        <div v-if="knowledgeDomainsLoading" class="mt-4 text-sm text-gray-500 dark:text-gray-400">加载规则域中...</div>
        <el-empty v-else-if="!knowledgeDomains.length" description="暂无规则域。导入时选择“局部生效规则域”可创建。" />
        <div v-else class="mt-4 grid gap-3 lg:grid-cols-2">
          <article
            v-for="domain in knowledgeDomains"
            :key="domain.id"
            class="rounded-2xl border border-gray-200 bg-gray-50/80 p-4 dark:border-gray-700 dark:bg-gray-900/50"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span class="font-semibold text-gray-900 dark:text-gray-100">{{ domain.name }}</span>
                  <span class="text-xs text-gray-500 dark:text-gray-400">添加时间：{{ formatTimestamp(domain.created_at) }}</span>
                </div>
                <div class="mt-1 flex flex-wrap gap-2 text-xs">
                  <el-tag size="small" :type="domain.is_active ? 'success' : 'info'">{{ domain.is_active ? '启用' : '禁用' }}</el-tag>
                  <el-tag size="small" type="info">{{ domainStatusLabel(domain.scope_status) }}</el-tag>
                  <el-tag size="small" type="warning">{{ activationModeLabel(domain.activation_mode) }}</el-tag>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <el-button
                  v-if="firstSuggestedVolume(domain)"
                  size="small"
                  plain
                  @click="confirmSuggestedDomain(domain)"
                >
                  确认用于{{ firstSuggestedVolume(domain) }}
                </el-button>
                <el-button
                  v-if="domain.is_active"
                  size="small"
                  type="danger"
                  plain
                  @click="disableDomain(domain)"
                >
                  禁用
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  plain
                  :loading="deletingDomainId === domain.id"
                  :disabled="!!deletingDomainId && deletingDomainId !== domain.id"
                  @click="deleteDomain(domain)"
                >
                  删除
                </el-button>
              </div>
            </div>
            <div class="mt-3 text-sm text-gray-600 dark:text-gray-300">
              <span class="font-medium text-gray-800 dark:text-gray-100">关键词：</span>
              {{ domainKeywordSummary(domain) }}
            </div>
            <div class="mt-2 text-sm text-gray-600 dark:text-gray-300">
              <span class="font-medium text-gray-800 dark:text-gray-100">建议范围：</span>
              {{ scopeSummary(domain.suggested_scopes) || '暂无' }}
            </div>
            <div class="mt-2 text-sm text-gray-600 dark:text-gray-300">
              <span class="font-medium text-gray-800 dark:text-gray-100">已确认：</span>
              {{ scopeSummary(domain.confirmed_scopes) || '暂无' }}
            </div>
            <div v-if="domainRuleSummary(domain)" class="mt-3 rounded-xl border border-gray-200 bg-white p-3 text-sm text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200">
              {{ domainRuleSummary(domain) }}
            </div>
            <div class="mt-3 flex justify-end">
              <button
                type="button"
                class="documents-library-card__edit"
                @click="openDomainDetail(domain)"
              >
                查看详情
              </button>
            </div>
          </article>
        </div>
      </div>

      <div v-if="reviewRecordRows.length" class="surface-card documents-panel documents-panel--reviews documents-pending p-5">
        <h3 class="font-bold">审核记录</h3>
        <p class="mt-1 mb-3 text-sm text-gray-500 dark:text-gray-400">
          这里统一显示导入资料、AI 设定会话和后续优化产生的待审核变更。
        </p>
        <el-table :data="reviewRecordRows" class="documents-pending-table">
          <el-table-column prop="source_name" label="来源对象" min-width="180" />
          <el-table-column label="来源类型">
            <template #default="{ row }">{{ row.source_label }}</template>
          </el-table-column>
          <el-table-column label="类型">
            <template #default="{ row }">{{ row.type_label }}</template>
          </el-table-column>
          <el-table-column label="状态">
            <template #default="{ row }">{{ statusLabel(row.status) }}</template>
          </el-table-column>
          <el-table-column label="变更摘要" min-width="220">
            <template #default="{ row }">{{ row.review_summary || '-' }}</template>
          </el-table-column>
          <el-table-column label="创建时间">
            <template #default="{ row }">{{ formatTimestamp(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <div class="documents-pending-table__actions flex gap-2">
                <el-button
                  v-if="row.review_record_source === 'ai'"
                  size="small"
                  type="primary"
                  plain
                  class="documents-pending-table__action"
                  @click="openSettingReviewBatch(row)"
                >
                  审核
                </el-button>
                <el-button
                  v-if="row.review_record_source === 'ai'"
                  size="small"
                  type="info"
                  plain
                  class="documents-pending-table__action"
                  @click="openSourceSession(row.source_session_id)"
                >
                  查看会话
                </el-button>
                <el-button
                  v-else
                  size="small"
                  type="info"
                  plain
                  class="documents-pending-table__action"
                  @click="showDetail(row)"
                >
                  查看详情
                </el-button>
                <el-button
                  v-if="row.review_record_source === 'import' && row.status === 'pending'"
                  size="small"
                  type="primary"
                  :loading="approvingPendingId === row.id"
                  :disabled="(!!approvingPendingId && approvingPendingId !== row.id) || !!rejectingPendingId"
                  @click="approve(row.id)"
                >
                  {{ approvingPendingId === row.id ? '批准中...' : '批准' }}
                </el-button>
                <el-button
                  v-if="row.review_record_source === 'import' && row.status === 'pending'"
                  size="small"
                  type="danger"
                  plain
                  :loading="rejectingPendingId === row.id"
                  :disabled="(!!rejectingPendingId && rejectingPendingId !== row.id) || !!approvingPendingId"
                  @click="reject(row.id)"
                >
                  {{ rejectingPendingId === row.id ? '拒绝中...' : '拒绝' }}
                </el-button>
                <el-button
                  v-if="row.review_record_source === 'import' && row.status === 'failed'"
                  size="small"
                  type="danger"
                  plain
                  :loading="deletingPendingId === row.id"
                  :disabled="(!!deletingPendingId && deletingPendingId !== row.id) || !!approvingPendingId || !!rejectingPendingId"
                  @click="removeFailedRecord(row.id)"
                >
                  {{ deletingPendingId === row.id ? '删除中...' : '删除' }}
                </el-button>
                <el-button
                  v-if="row.review_record_source === 'import' && row.status === 'processing'"
                  size="small"
                  type="warning"
                  plain
                  :loading="deletingPendingId === row.id"
                  :disabled="!!deletingPendingId && deletingPendingId !== row.id"
                  @click="cancelProcessingRecord(row.id)"
                >
                  {{ deletingPendingId === row.id ? '取消中...' : '取消' }}
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
        </div>
      </section>

      <el-dialog
        v-model="detailVisible"
        title="导入详情"
        width="1080px"
        top="4vh"
        append-to-body
        :close-on-press-escape="false"
      >
        <div v-if="selectedDoc" class="max-h-[78vh] space-y-4 overflow-y-auto pr-2">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div><span class="font-bold">类型：</span>{{ extractionTypeLabel(selectedDoc.extraction_type, selectedDoc.status) }}</div>
            <div><span class="font-bold">状态：</span>{{ statusLabel(selectedDoc.status) }}</div>
            <div><span class="font-bold">创建时间：</span>{{ formatTimestamp(selectedDoc.created_at) }}</div>
          </div>

          <el-alert
            v-if="selectedDoc.error_message"
            :title="selectedDoc.error_message"
            type="error"
            :closable="false"
            show-icon
          />

          <el-alert
            v-if="mergeResolvingCount"
            :title="`自动合并中：${mergeResolvingCount} 个冲突字段正在处理`"
            type="warning"
            :closable="false"
            show-icon
          />

          <div v-if="selectedDoc.diff_result" class="space-y-3">
            <div class="flex items-center justify-between">
              <div class="font-bold">增量变更</div>
              <span class="text-sm text-gray-500">{{ selectedDoc.diff_result.summary }}</span>
            </div>

            <div v-if="diffGroups.create.length">
              <div class="font-semibold mb-2 text-green-700 dark:text-green-300">新增实体</div>
              <div class="space-y-2">
                <div v-for="entity in diffGroups.create" :key="entityKey(entity)" class="rounded-lg border border-green-200 dark:border-green-800 p-3 bg-green-50/60 dark:bg-green-950/20">
                  <div class="font-semibold mb-2">{{ entity.entity_name }} <span class="text-xs text-gray-500">{{ entity.entity_type }}</span></div>
                  <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
                    <div
                      v-for="change in visibleChanges(entity)"
                      :key="change.field"
                      class="documents-draft-field group rounded-lg border border-transparent px-2 py-2 hover:border-green-200/70 dark:hover:border-green-700/70"
                    >
                      <div class="flex items-start gap-2">
                        <span class="font-medium min-w-20">{{ change.label || change.field }}：</span>
                        <div class="min-w-0 flex-1">
                          <template v-if="isEditingDraftField(entity, change)">
                            <textarea
                              v-if="isMultilineDraftField(change.field)"
                              v-model="draftFieldInput"
                              class="documents-draft-field__input documents-draft-field__input--textarea"
                              :disabled="isSavingDraftField(entity, change)"
                              @keydown.enter.exact.prevent="saveDraftFieldEdit"
                              @keydown.esc.stop.prevent="cancelDraftFieldEdit"
                            />
                            <input
                              v-else
                              v-model="draftFieldInput"
                              class="documents-draft-field__input"
                              :disabled="isSavingDraftField(entity, change)"
                              @keydown.enter.exact.prevent="saveDraftFieldEdit"
                              @keydown.esc.stop.prevent="cancelDraftFieldEdit"
                            />
                            <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">回车保存，Esc 取消</div>
                            <div v-if="draftFieldError" class="mt-1 text-xs text-red-600 dark:text-red-400">{{ draftFieldError }}</div>
                          </template>
                          <span v-else class="whitespace-pre-wrap">{{ formatValue(change.new_value) }}</span>
                        </div>
                        <button
                          v-if="!isEditingDraftField(entity, change)"
                          type="button"
                          class="documents-draft-field__edit"
                          title="编辑字段"
                          aria-label="编辑字段"
                          @click="beginDraftFieldEdit(entity, change)"
                        >
                          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" class="documents-draft-field__edit-icon">
                            <path d="M13.96 3.64a1.5 1.5 0 0 1 2.12 0l.28.28a1.5 1.5 0 0 1 0 2.12l-8.9 8.9-3.32.94.94-3.32 8.88-8.92Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                            <path d="M12.5 5.1l2.4 2.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="diffGroups.update.length">
              <div class="font-semibold mb-2 text-blue-700 dark:text-blue-300">自动补充</div>
              <div class="space-y-2">
                <div v-for="entity in diffGroups.update" :key="entityKey(entity)" class="rounded-lg border border-blue-200 dark:border-blue-800 p-3 bg-blue-50/60 dark:bg-blue-950/20">
                  <div class="font-semibold mb-2">{{ entity.entity_name }} <span class="text-xs text-gray-500">{{ entity.entity_type }}</span></div>
                  <el-table :data="visibleChanges(entity)" size="small" border class="documents-detail-table">
                    <el-table-column prop="label" label="字段" width="120">
                      <template #default="{ row }">{{ row.label || row.field }}</template>
                    </el-table-column>
                    <el-table-column label="旧值">
                      <template #default="{ row }"><span class="whitespace-pre-wrap">{{ formatValue(row.old_value) || '-' }}</span></template>
                    </el-table-column>
                    <el-table-column label="新值">
                      <template #default="{ row }">
                        <div class="documents-draft-field group rounded-lg border border-transparent px-2 py-2 hover:border-blue-200/70 dark:hover:border-blue-700/70">
                          <div class="flex items-start gap-2">
                            <div class="min-w-0 flex-1">
                              <template v-if="isEditingDraftField(entity, row)">
                                <textarea
                                  v-if="isMultilineDraftField(row.field)"
                                  v-model="draftFieldInput"
                                  class="documents-draft-field__input documents-draft-field__input--textarea"
                                  :disabled="isSavingDraftField(entity, row)"
                                  @keydown.enter.exact.prevent="saveDraftFieldEdit"
                                  @keydown.esc.stop.prevent="cancelDraftFieldEdit"
                                />
                                <input
                                  v-else
                                  v-model="draftFieldInput"
                                  class="documents-draft-field__input"
                                  :disabled="isSavingDraftField(entity, row)"
                                  @keydown.enter.exact.prevent="saveDraftFieldEdit"
                                  @keydown.esc.stop.prevent="cancelDraftFieldEdit"
                                />
                                <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">回车保存，Esc 取消</div>
                                <div v-if="draftFieldError" class="mt-1 text-xs text-red-600 dark:text-red-400">{{ draftFieldError }}</div>
                              </template>
                              <span v-else class="whitespace-pre-wrap">{{ formatValue(row.new_value) }}</span>
                            </div>
                            <button
                              v-if="!isEditingDraftField(entity, row)"
                              type="button"
                              class="documents-draft-field__edit"
                              title="编辑字段"
                              aria-label="编辑字段"
                              @click="beginDraftFieldEdit(entity, row)"
                            >
                              <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" class="documents-draft-field__edit-icon">
                                <path d="M13.96 3.64a1.5 1.5 0 0 1 2.12 0l.28.28a1.5 1.5 0 0 1 0 2.12l-8.9 8.9-3.32.94.94-3.32 8.88-8.92Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                                <path d="M12.5 5.1l2.4 2.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                              </svg>
                            </button>
                          </div>
                        </div>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </div>
            </div>

            <div v-if="diffGroups.conflict.length">
              <div class="font-semibold mb-2 text-red-700 dark:text-red-300">冲突字段</div>
              <div class="space-y-2">
                <div v-for="entity in diffGroups.conflict" :key="entityKey(entity)" class="rounded-lg border border-red-200 dark:border-red-800 p-3 bg-red-50/60 dark:bg-red-950/20">
                  <div class="font-semibold mb-2">{{ entity.entity_name }} <span class="text-xs text-gray-500">{{ entity.entity_type }}</span></div>
                  <el-table :data="visibleChanges(entity)" size="small" border class="documents-detail-table">
                    <el-table-column prop="label" label="字段" width="120">
                      <template #default="{ row }">{{ row.label || row.field }}</template>
                    </el-table-column>
                    <el-table-column label="旧值">
                      <template #default="{ row }"><span class="whitespace-pre-wrap">{{ formatValue(row.old_value) || '-' }}</span></template>
                    </el-table-column>
                    <el-table-column label="新值">
                      <template #default="{ row }">
                        <div class="documents-draft-field group rounded-lg border border-transparent px-2 py-2 hover:border-red-200/70 dark:hover:border-red-700/70">
                          <div class="flex items-start gap-2">
                            <div class="min-w-0 flex-1">
                              <template v-if="isEditingDraftField(entity, row)">
                                <textarea
                                  v-if="isMultilineDraftField(row.field)"
                                  v-model="draftFieldInput"
                                  class="documents-draft-field__input documents-draft-field__input--textarea"
                                  :disabled="isSavingDraftField(entity, row)"
                                  @keydown.enter.exact.prevent="saveDraftFieldEdit"
                                  @keydown.esc.stop.prevent="cancelDraftFieldEdit"
                                />
                                <input
                                  v-else
                                  v-model="draftFieldInput"
                                  class="documents-draft-field__input"
                                  :disabled="isSavingDraftField(entity, row)"
                                  @keydown.enter.exact.prevent="saveDraftFieldEdit"
                                  @keydown.esc.stop.prevent="cancelDraftFieldEdit"
                                />
                                <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">回车保存，Esc 取消</div>
                                <div v-if="draftFieldError" class="mt-1 text-xs text-red-600 dark:text-red-400">{{ draftFieldError }}</div>
                              </template>
                              <span v-else class="whitespace-pre-wrap">{{ formatValue(row.new_value) }}</span>
                            </div>
                            <button
                              v-if="!isEditingDraftField(entity, row)"
                              type="button"
                              class="documents-draft-field__edit"
                              title="编辑字段"
                              aria-label="编辑字段"
                              @click="beginDraftFieldEdit(entity, row)"
                            >
                              <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" class="documents-draft-field__edit-icon">
                                <path d="M13.96 3.64a1.5 1.5 0 0 1 2.12 0l.28.28a1.5 1.5 0 0 1 0 2.12l-8.9 8.9-3.32.94.94-3.32 8.88-8.92Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                                <path d="M12.5 5.1l2.4 2.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                              </svg>
                            </button>
                          </div>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="处理方式" width="180">
                      <template #default="{ row }">
                        <el-tag v-if="row.auto_applicable" type="success" size="small">默认采用新值</el-tag>
                        <el-tag
                          v-else-if="isMergeResolving(entity, row)"
                          type="warning"
                          size="small"
                        >
                          自动合并中
                        </el-tag>
                        <el-select
                          v-else
                          v-model="conflictSelections[conflictKey(entity, row)]"
                          size="small"
                          :disabled="isApprovingSelectedDoc"
                        >
                          <el-option label="保留旧值" value="keep_old" />
                          <el-option label="使用新值" value="use_new" />
                          <el-option label="自动合并" value="merge" />
                          <el-option label="跳过" value="skip" />
                        </el-select>
                      </template>
                    </el-table-column>
                    <el-table-column prop="reason" label="原因" width="180" />
                  </el-table>
                </div>
              </div>
            </div>

            <el-empty v-if="!selectedDoc.diff_result.entity_diffs?.length" description="无实体变更" />
          </div>

          <div v-if="resolutionRows.length">
            <div class="font-semibold mb-2 text-purple-700 dark:text-purple-300">处理结果</div>
            <el-table :data="resolutionRows" size="small" border class="documents-detail-table">
              <el-table-column prop="entity_name" label="实体" width="140" />
              <el-table-column prop="field" label="字段" width="120">
                <template #default="{ row }">{{ fieldLabel(row.field) }}</template>
              </el-table-column>
              <el-table-column prop="action" label="动作" width="140">
                <template #default="{ row }">
                  <el-tag :type="row.applied ? 'success' : 'info'" size="small">{{ resolutionActionLabel(row.action) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="applied" label="是否写入" width="100">
                <template #default="{ row }">{{ row.applied ? '已写入' : '未写入' }}</template>
              </el-table-column>
            </el-table>
          </div>

          <el-collapse class="documents-detail-collapse">
            <el-collapse-item title="原始提取结果" name="raw" class="documents-detail-collapse__panel">
              <pre class="documents-detail-collapse__content bg-gray-50 dark:bg-gray-900 rounded-lg p-3 text-xs overflow-auto max-h-80 whitespace-pre-wrap">{{ formatJson(selectedDoc.raw_result) }}</pre>
            </el-collapse-item>
            <el-collapse-item title="拟写入实体" name="entities" class="documents-detail-collapse__panel">
              <pre class="documents-detail-collapse__content bg-gray-50 dark:bg-gray-900 rounded-lg p-3 text-xs overflow-auto max-h-80 whitespace-pre-wrap">{{ formatJson(selectedDoc.proposed_entities) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-dialog>

      <el-dialog
        v-model="libraryDetailVisible"
        :title="libraryDetailTitle"
        width="980px"
        top="6vh"
        append-to-body
      >
        <div v-if="selectedLibraryItem" class="max-h-[76vh] space-y-4 overflow-y-auto pr-2">
          <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 p-3 text-sm dark:border-gray-700">
            <div>
              <div class="font-semibold text-gray-900 dark:text-gray-100">{{ selectedLibraryItem.title || selectedLibraryLabel }}</div>
              <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {{ selectedLibraryLabel }} · v{{ selectedLibraryItem.version || 1 }} · {{ formatTimestamp(selectedLibraryItem.updated_at) }}
              </div>
            </div>
            <button
              type="button"
              class="documents-library-card__edit"
              @click="openLibraryEditor(selectedLibraryItem, selectedLibraryLabel)"
            >
              编辑
            </button>
          </div>
          <pre class="documents-library-detail__content whitespace-pre-wrap rounded-2xl border border-gray-200 bg-gray-50 p-4 text-sm leading-7 text-gray-700 dark:border-gray-700 dark:bg-gray-900/60 dark:text-gray-200">{{ selectedLibraryItem.content }}</pre>

          <div v-if="selectedLibraryItem.doc_type === 'style_profile'" class="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
            <div class="font-semibold text-gray-900 dark:text-gray-100">完整风格配置</div>
            <pre class="mt-3 whitespace-pre-wrap text-xs leading-6 text-gray-600 dark:text-gray-300">{{ formatJson(selectedLibraryItem.style_config || {}) }}</pre>
          </div>
        </div>
      </el-dialog>

      <el-dialog
        v-model="domainDetailVisible"
        title="规则域详情"
        width="900px"
        top="6vh"
        append-to-body
      >
        <div v-if="selectedDomain" class="max-h-[76vh] space-y-4 overflow-y-auto pr-2">
          <div class="rounded-xl border border-gray-200 p-3 text-sm dark:border-gray-700">
            <div class="font-semibold text-gray-900 dark:text-gray-100">{{ selectedDomain.name }}</div>
            <div class="mt-2 flex flex-wrap gap-2 text-xs">
              <el-tag size="small" :type="selectedDomain.is_active ? 'success' : 'info'">{{ selectedDomain.is_active ? '启用' : '禁用' }}</el-tag>
              <el-tag size="small" type="info">{{ domainStatusLabel(selectedDomain.scope_status) }}</el-tag>
              <el-tag size="small" type="warning">{{ activationModeLabel(selectedDomain.activation_mode) }}</el-tag>
            </div>
          </div>
          <div class="grid gap-3 md:grid-cols-2 text-sm">
            <div class="rounded-xl border border-gray-200 p-3 dark:border-gray-700">
              <div class="text-xs text-gray-400">关键词</div>
              <div class="mt-1 text-gray-700 dark:text-gray-200">{{ (selectedDomain.activation_keywords || []).join('、') || '未设置' }}</div>
            </div>
            <div class="rounded-xl border border-gray-200 p-3 dark:border-gray-700">
              <div class="text-xs text-gray-400">绑定范围</div>
              <div class="mt-1 text-gray-700 dark:text-gray-200">
                建议：{{ scopeSummary(selectedDomain.suggested_scopes) || '暂无' }}；已确认：{{ scopeSummary(selectedDomain.confirmed_scopes) || '暂无' }}
              </div>
            </div>
          </div>
          <div class="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
            <div class="font-semibold text-gray-900 dark:text-gray-100">完整规则</div>
            <pre class="mt-3 whitespace-pre-wrap text-sm leading-7 text-gray-700 dark:text-gray-200">{{ formatJson(selectedDomain.rules || {}) }}</pre>
          </div>
        </div>
      </el-dialog>

      <el-dialog
        v-model="styleVersionsVisible"
        title="文风版本"
        width="980px"
        top="6vh"
        append-to-body
      >
        <div v-if="styleVersionsVisible" class="max-h-[76vh] space-y-3 overflow-y-auto pr-2">
          <div
            v-for="profile in styleProfiles"
            :key="profile.id"
            class="rounded-xl border border-gray-200 bg-gray-50/70 p-4 dark:border-gray-700 dark:bg-gray-900/50"
          >
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="flex items-center gap-2">
                <div class="font-medium text-gray-900 dark:text-gray-100">版本 v{{ profile.version }}</div>
                <el-tag v-if="profile.is_active" size="small" type="success">当前生效</el-tag>
                <el-tag v-else size="small" type="info">历史版本</el-tag>
              </div>
              <div class="flex items-center gap-2">
                <div class="text-xs text-gray-500 dark:text-gray-400">{{ formatTimestamp(profile.updated_at) }}</div>
                <button type="button" class="documents-library-card__edit" @click="openLibraryDetail(profile, '文风档案')">
                  查看详情
                </button>
                <button type="button" class="documents-library-card__edit" @click="openLibraryEditor(profile, '文风档案')">
                  编辑
                </button>
                <el-button
                  v-if="!profile.is_active"
                  size="small"
                  :loading="rollingBackVersion === profile.version"
                  @click="activateStyleVersion(profile.version)"
                >
                  {{ rollingBackVersion === profile.version ? '切换中...' : '设为当前版本' }}
                </el-button>
              </div>
            </div>

            <div class="mt-3 line-clamp-3 whitespace-pre-wrap rounded-xl border border-gray-200 bg-white p-3 text-sm leading-6 text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200">
              {{ profile.content }}
            </div>
          </div>
        </div>
      </el-dialog>

      <el-dialog
        v-model="libraryEditorVisible"
        :title="libraryEditorTitle"
        width="880px"
        top="8vh"
        append-to-body
      >
        <div class="space-y-4">
          <div class="text-sm text-gray-500 dark:text-gray-400">
            保存后会生成该资料的新版本，并立即作为当前资料库内容生效。
          </div>
          <textarea
            v-model="libraryEditorContent"
            class="documents-library-editor__textarea"
            :disabled="libraryEditorSaving"
          />
          <div v-if="libraryEditorError" class="text-sm text-red-600 dark:text-red-400">{{ libraryEditorError }}</div>
          <div class="flex justify-end gap-2">
            <el-button :disabled="libraryEditorSaving" @click="closeLibraryEditor">取消</el-button>
            <el-button type="primary" :loading="libraryEditorSaving" @click="saveLibraryEditor">
              {{ libraryEditorSaving ? '保存中...' : '保存为新版本' }}
            </el-button>
          </div>
        </div>
      </el-dialog>

      <el-dialog
        v-model="settingReviewVisible"
        title="审核设定变更"
        width="1080px"
        top="5vh"
        append-to-body
      >
        <div v-if="settingReviewVisible" class="max-h-[76vh] space-y-4 overflow-y-auto pr-2">
          <div v-if="settingReviewLoading" class="text-sm text-gray-500 dark:text-gray-400">加载审核记录中...</div>
          <template v-else-if="selectedSettingReviewBatch">
            <div class="rounded-xl border border-gray-200 p-3 text-sm dark:border-gray-700">
              <div class="font-semibold text-gray-900 dark:text-gray-100">{{ selectedSettingReviewBatch.summary || '未命名审核记录' }}</div>
              <div class="mt-2 flex flex-wrap gap-2 text-xs text-gray-500 dark:text-gray-400">
                <span>状态：{{ statusLabel(selectedSettingReviewBatch.status) }}</span>
                <span>{{ countsLabel(selectedSettingReviewBatch.counts) }}</span>
              </div>
            </div>

            <div class="space-y-3">
              <article
                v-for="change in selectedSettingReviewBatch.changes || []"
                :key="change.id"
                class="documents-setting-review-change"
              >
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="font-semibold text-gray-900 dark:text-gray-100">{{ settingChangeTitle(change) }}</div>
                    <div class="mt-1 flex flex-wrap gap-2 text-xs text-gray-500 dark:text-gray-400">
                      <span>{{ settingChangeTargetLabel(change.target_type) }}</span>
                      <span>{{ settingChangeOperationLabel(change.operation) }}</span>
                      <span>{{ statusLabel(change.status) }}</span>
                    </div>
                  </div>
                  <div class="flex flex-wrap justify-end gap-2">
                    <el-button
                      size="small"
                      plain
                      @click="openSettingReviewChangeDetail(change)"
                    >
                      查看详情
                    </el-button>
                    <template v-if="change.status === 'pending'">
                      <el-button
                        size="small"
                        type="danger"
                        plain
                        :loading="settingReviewApplying"
                        :disabled="settingReviewApplying"
                        @click="applySettingReviewDecision('reject', change)"
                      >
                        拒绝
                      </el-button>
                      <el-button
                        size="small"
                        type="primary"
                        :loading="settingReviewApplying"
                        :disabled="settingReviewApplying"
                        @click="applySettingReviewDecision('approve', change)"
                      >
                        批准
                      </el-button>
                    </template>
                  </div>
                </div>
                <p class="mt-3 whitespace-pre-wrap text-sm leading-6 text-gray-700 dark:text-gray-200">
                  {{ settingChangeSummary(change) }}
                </p>
              </article>
            </div>

            <div class="flex flex-wrap justify-end gap-2">
              <el-button
                type="danger"
                plain
                :loading="settingReviewApplying"
                :disabled="!pendingSettingReviewChanges.length || settingReviewApplying"
                @click="applySettingReviewDecision('reject')"
              >
                拒绝全部
              </el-button>
              <el-button
                type="primary"
                :loading="settingReviewApplying"
                :disabled="!pendingSettingReviewChanges.length || settingReviewApplying"
                @click="applySettingReviewDecision('approve')"
              >
                批准全部
              </el-button>
            </div>
          </template>
        </div>
      </el-dialog>

      <el-dialog
        v-model="settingReviewChangeDetailVisible"
        title="设定变更详情"
        width="920px"
        top="7vh"
        append-to-body
      >
        <div v-if="selectedSettingReviewChange" class="max-h-[72vh] space-y-4 overflow-y-auto pr-2 text-sm">
          <div class="rounded-xl border border-gray-200 p-3 dark:border-gray-700">
            <div class="font-semibold text-gray-900 dark:text-gray-100">
              {{ settingChangeTitle(selectedSettingReviewChange) }}
            </div>
            <div class="mt-2 flex flex-wrap gap-2 text-xs text-gray-500 dark:text-gray-400">
              <span>{{ settingChangeTargetLabel(selectedSettingReviewChange.target_type) }}</span>
              <span>{{ settingChangeOperationLabel(selectedSettingReviewChange.operation) }}</span>
              <span>{{ statusLabel(selectedSettingReviewChange.status) }}</span>
            </div>
          </div>

          <section
            v-for="section in settingReviewDetailSections(selectedSettingReviewChange)"
            :key="section.key"
            class="documents-setting-review-detail-section"
          >
            <h4>{{ section.title }}</h4>
            <dl v-if="section.rows?.length" class="documents-setting-review-detail-fields">
              <div
                v-for="row in section.rows"
                :key="row.key"
                class="documents-setting-review-detail-field"
              >
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>
            <pre v-else>{{ section.content }}</pre>
          </section>
          <section v-if="selectedSettingReviewChange.conflict_hints?.length" class="documents-setting-review-detail-section">
            <h4>冲突提示</h4>
            <pre>{{ formatReadableValue(selectedSettingReviewChange.conflict_hints) }}</pre>
          </section>
          <section v-if="selectedSettingReviewChange.error_message" class="documents-setting-review-detail-section">
            <h4>错误信息</h4>
            <pre>{{ selectedSettingReviewChange.error_message }}</pre>
          </section>
        </div>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNovelStore } from '@/stores/novel.js'
import SettingWorkbench from '@/views/SettingWorkbench.vue'
import {
  uploadDocumentsBatch,
  approvePending,
  updatePendingDraftField,
  deletePendingDoc,
  rejectPending,
  getDocumentLibrary,
  updateLibraryDocument,
  rollbackStyleProfile,
  getSettingReviewBatch,
  applySettingReviewBatch,
} from '@/api.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatBeijingDateTime } from '@/utils/time.js'

const DOCUMENT_POLL_INTERVAL_MS = 2000
const LIBRARY_GROUPS = [
  { docType: 'worldview', label: '世界观' },
  { docType: 'setting', label: '体系设定' },
  { docType: 'synopsis', label: '剧情梗概' },
  { docType: 'concept', label: '概念设定' },
]

const store = useNovelStore()
const route = useRoute()
const router = useRouter()
const fileInput = ref(null)
const selectedFiles = ref([])
const uploading = ref(false)
const activeKnowledgeTab = ref(route.query?.tab === 'ai' ? 'ai' : 'import')
const knowledgeUsage = ref('auto')
const domainName = ref('')
const knowledgeDomainsLoading = ref(false)
const deletingDomainId = ref('')
const domainDetailVisible = ref(false)
const selectedDomain = ref(null)
const detailVisible = ref(false)
const selectedDoc = ref(null)
const conflictSelections = reactive({})
const conflictSelectionMemory = reactive({})
const resolvingMergeKeys = reactive({})
const uploadSummary = ref(null)
const documentPollTimer = ref(null)
let draftFieldEscapeListenerAttached = false
const libraryItems = ref([])
const libraryLoading = ref(false)
const rollingBackVersion = ref(null)
const libraryDetailVisible = ref(false)
const selectedLibraryItem = ref(null)
const selectedLibraryLabel = ref('')
const styleVersionsVisible = ref(false)
const libraryEditorVisible = ref(false)
const libraryEditorTarget = ref(null)
const libraryEditorContent = ref('')
const libraryEditorError = ref('')
const libraryEditorSaving = ref(false)
const settingReviewVisible = ref(false)
const settingReviewLoading = ref(false)
const settingReviewApplying = ref(false)
const selectedSettingReviewBatch = ref(null)
const settingReviewChangeDetailVisible = ref(false)
const selectedSettingReviewChange = ref(null)
const editingDraftField = ref(null)
const draftFieldInput = ref('')
const draftFieldError = ref('')
const savingDraftFieldKey = ref('')
const approvingPendingId = computed({
  get: () => store.pendingDocActions.approvingPendingId,
  set: (value) => {
    store.pendingDocActions.approvingPendingId = value
  },
})
const rejectingPendingId = computed({
  get: () => store.pendingDocActions.rejectingPendingId,
  set: (value) => {
    store.pendingDocActions.rejectingPendingId = value
  },
})
const deletingPendingId = computed({
  get: () => store.pendingDocActions.deletingPendingId,
  set: (value) => {
    store.pendingDocActions.deletingPendingId = value
  },
})

const diffGroups = computed(() => {
  const groups = { create: [], update: [], conflict: [] }
  for (const entity of selectedDoc.value?.diff_result?.entity_diffs || []) {
    if (entity.operation === 'create') groups.create.push(entity)
    else if (entity.operation === 'conflict') groups.conflict.push(entity)
    else if (entity.operation === 'update') groups.update.push(entity)
  }
  return groups
})

const resolutionRows = computed(() => selectedDoc.value?.resolution_result?.field_resolutions || [])
const importRecordRows = computed(() => {
  const docs = store.pendingDocs || []
  const rank = { processing: 0, pending: 1, failed: 2, approved: 3, rejected: 4 }
  return [...docs].map((doc) => ({
    ...doc,
    review_record_source: 'import',
    source_label: '导入资料',
    source_name: doc.source_filename || '导入资料',
    type_label: extractionTypeLabel(doc.extraction_type, doc.status),
    review_summary: doc.diff_result?.summary || doc.error_message || '-',
  })).sort((left, right) => {
    const leftRank = rank[left.status] ?? 9
    const rightRank = rank[right.status] ?? 9
    if (leftRank !== rightRank) return leftRank - rightRank
    return String(right.created_at || '').localeCompare(String(left.created_at || ''))
  })
})
const aiReviewRecordRows = computed(() => {
  const batches = store.settingWorkbench?.reviewBatches || []
  return batches.map((batch) => ({
    ...batch,
    review_record_source: 'ai',
    source_label: 'AI 会话',
    source_name: batch.source_session_title || 'AI 设定会话',
    type_label: countsLabel(batch.counts),
    review_summary: batch.summary || batch.error_message || '-',
  }))
})
const reviewRecordRows = computed(() => {
  const rank = { processing: 0, pending: 1, failed: 2, approved: 3, partially_approved: 3, rejected: 4, generated: 5 }
  return [...importRecordRows.value, ...aiReviewRecordRows.value].sort((left, right) => {
    const leftRank = rank[left.status] ?? 9
    const rightRank = rank[right.status] ?? 9
    if (leftRank !== rightRank) return leftRank - rightRank
    return String(right.created_at || '').localeCompare(String(left.created_at || ''))
  })
})
const activeImportDocs = computed(() => (
  importRecordRows.value.filter((doc) => ['processing', 'pending', 'failed'].includes(doc.status))
))
const activeReviewRecords = computed(() => (
  reviewRecordRows.value.filter((row) => ['processing', 'pending', 'failed'].includes(row.status))
))
const hasProcessingDocs = computed(() => activeImportDocs.value.some((doc) => doc.status === 'processing'))
const pendingReviewCount = computed(() => (
  activeReviewRecords.value.filter((row) => row.status === 'pending' || row.status === 'processing').length
))
const isApprovingSelectedDoc = computed(() => !!selectedDoc.value?.id && approvingPendingId.value === selectedDoc.value.id)
const mergeResolvingCount = computed(() => Object.keys(resolvingMergeKeys).length)
const hasLibraryContent = computed(() => libraryItems.value.length > 0)
const styleProfiles = computed(() => libraryItems.value.filter((item) => item.doc_type === 'style_profile'))
const activeStyleProfile = computed(() => styleProfiles.value.find((item) => item.is_active) || styleProfiles.value[0] || null)
const activeStyleVersionText = computed(() => {
  return activeStyleProfile.value ? `v${activeStyleProfile.value.version}` : '未设置'
})
const libraryDetailTitle = computed(() => {
  if (!selectedLibraryItem.value) return '资料详情'
  return `${selectedLibraryLabel.value || '资料'}详情`
})
const knowledgeDomains = computed(() => store.knowledgeDomains || [])
const libraryEditorTitle = computed(() => {
  const target = libraryEditorTarget.value
  if (!target) return '编辑资料'
  return `编辑${target.groupLabel || target.title || '资料'}`
})
const libraryGroups = computed(() =>
  LIBRARY_GROUPS
    .map((group) => ({
      ...group,
      items: libraryItems.value.filter((item) => item.doc_type === group.docType),
    }))
    .filter((group) => group.items.length)
)
const pendingSettingReviewChanges = computed(() =>
  (selectedSettingReviewBatch.value?.changes || []).filter((change) => change.status === 'pending')
)

const fieldLabels = {
  name: '名称',
  identity: '身份',
  personality: '性格',
  goal: '目标',
  appearance: '外貌',
  background: '背景',
  ability: '能力',
  realm: '境界',
  relationships: '关系',
  resources: '资源',
  secrets: '秘密',
  conflict: '冲突',
  arc: '人物弧光',
  notes: '备注',
  description: '描述',
  significance: '重要性',
}

const multilineDraftFields = new Set([
  'description',
  'background',
  'relationships',
  'resources',
  'secrets',
  'conflict',
  'arc',
  'notes',
  'significance',
])

function fieldLabel(field) {
  return fieldLabels[field] || field
}

function extractionTypeLabel(type, status = '') {
  if (status === 'processing' && (!type || type === 'processing')) return '处理中'
  const labels = {
    setting: '设定',
    style_profile: '风格样本',
    processing: '处理中',
  }
  return labels[type] || type || '-'
}

function statusLabel(status) {
  const labels = {
    processing: '导入中',
    pending: '待审核',
    failed: '失败',
    approved: '已批准',
    partially_approved: '部分批准',
    rejected: '已拒绝',
    generated: '已生成',
  }
  return labels[status] || status || '-'
}

function countsLabel(counts = {}) {
  const settingCards = counts.setting_card ?? counts.setting_cards ?? counts.cards ?? 0
  const entities = counts.entity ?? counts.entities ?? 0
  const relationships = counts.relationship ?? counts.relationships ?? 0
  return `设定卡片 ${settingCards} · 实体 ${entities} · 关系 ${relationships}`
}

function settingChangeTargetLabel(targetType) {
  const labels = {
    setting_card: '设定卡片',
    entity: '实体',
    relationship: '关系',
  }
  return labels[targetType] || targetType || '-'
}

function settingChangeOperationLabel(operation) {
  const labels = {
    create: '新增',
    update: '修改',
    delete: '删除',
  }
  return labels[operation] || operation || '-'
}

function settingChangeTitle(change) {
  const snapshot = change.after_snapshot || change.before_snapshot || {}
  if (change.target_type === 'setting_card') return snapshot.title || change.target_id || '未命名设定卡片'
  if (change.target_type === 'entity') return snapshot.name || change.target_id || '未命名实体'
  if (change.target_type === 'relationship') {
    return [snapshot.source_name || snapshot.source_id, snapshot.relation_type, snapshot.target_name || snapshot.target_id]
      .filter(Boolean)
      .join(' / ') || '实体关系'
  }
  return change.target_id || '未命名变更'
}

function settingChangeSummary(change) {
  const snapshot = change.after_snapshot || change.before_snapshot || {}
  if (change.target_type === 'setting_card') return summarizeContent(snapshot.content || snapshot.doc_type || '', 360)
  if (change.target_type === 'entity') return summarizeContent(snapshot.state || snapshot.data || snapshot, 360)
  if (change.target_type === 'relationship') return summarizeContent(snapshot, 260)
  return summarizeContent(snapshot, 260)
}

function normalizeSettingReviewBatchPayload(payload) {
  if (!payload) return null
  if (payload.batch) {
    return {
      ...payload.batch,
      changes: payload.changes || [],
    }
  }
  return {
    ...payload,
    changes: payload.changes || [],
  }
}

function resolutionActionLabel(action) {
  const labels = {
    created: '新增实体',
    auto_apply: '自动写入',
    use_new: '采用新值',
    merge: '自动合并',
    keep_old: '保留旧值',
    skip: '跳过',
  }
  return labels[action] || action
}

function formatTimestamp(value) {
  return formatBeijingDateTime(value)
}

function formatJson(value) {
  if (value == null) return '-'
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function formatValue(value) {
  if (value == null || value === '') return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

const settingReviewSnapshotFieldLabels = {
  doc_type: '资料类型',
  title: '标题',
  content: '正文',
  type: '类型',
  name: '名称',
  state: '状态',
  data: '数据',
  source_id: '源实体',
  source_name: '源实体',
  relation_type: '关系',
  target_id: '目标实体',
  target_name: '目标实体',
  description: '描述',
}

const settingReviewSnapshotFieldOrder = [
  'title',
  'name',
  'doc_type',
  'type',
  'content',
  'description',
  'state',
  'data',
  'source_name',
  'source_id',
  'relation_type',
  'target_name',
  'target_id',
]

function normalizeReadableText(value) {
  return String(value)
    .replace(/\\r\\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '  ')
}

function formatReadableValue(value) {
  if (value == null || value === '') return '-'
  if (typeof value === 'string') return normalizeReadableText(value)
  return normalizeReadableText(JSON.stringify(value, null, 2))
}

function orderedSnapshotEntries(snapshot = {}) {
  const keys = Object.keys(snapshot)
  const orderedKeys = [
    ...settingReviewSnapshotFieldOrder.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !settingReviewSnapshotFieldOrder.includes(key)).sort(),
  ]
  return orderedKeys.map((key) => [key, snapshot[key]])
}

function settingReviewSnapshotRows(snapshot = {}) {
  return orderedSnapshotEntries(snapshot)
    .filter(([, value]) => value != null && value !== '')
    .map(([key, value]) => ({
      key,
      label: settingReviewSnapshotFieldLabels[key] || key,
      value: formatReadableValue(value),
    }))
}

function settingReviewDetailSections(change) {
  const sections = []
  if (change?.after_snapshot) {
    sections.push({
      key: 'after',
      title: '变更后',
      rows: settingReviewSnapshotRows(change.after_snapshot),
      content: formatReadableValue(change.after_snapshot),
    })
  }
  if (change?.before_snapshot) {
    sections.push({
      key: 'before',
      title: '变更前',
      rows: settingReviewSnapshotRows(change.before_snapshot),
      content: formatReadableValue(change.before_snapshot),
    })
  }
  return sections
}

function summarizeContent(value, maxLength = 180) {
  const text = normalizeReadableText(formatValue(value)).replace(/\s+/g, ' ').trim()
  if (!text) return '暂无内容'
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

function normalizeDraftFieldValue(value) {
  return typeof value === 'string' ? value : formatValue(value)
}

function toList(value) {
  if (!Array.isArray(value)) return []
  return value.map((item) => formatValue(item)).filter(Boolean)
}

function styleSummaryItems(profile) {
  const config = profile?.style_config || {}
  const items = []
  if (config.perspective) items.push({ label: '叙事视角', value: config.perspective })
  if (config.pacing) items.push({ label: '节奏', value: config.pacing })
  if (config.tone) items.push({ label: '整体气质', value: config.tone })
  const writingRules = toList(config.writing_rules)
  if (writingRules.length) items.push({ label: '写作规则', value: writingRules.join('\n') })
  const boundaries = toList(config.style_boundary)
  if (boundaries.length) items.push({ label: '风格边界', value: boundaries.join('\n') })
  const vocabulary = toList(config.vocabulary_preferences)
  if (vocabulary.length) items.push({ label: '偏好词汇', value: vocabulary.join(' / ') })
  return items
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (ev) => resolve({ filename: file.name, content: ev.target.result || '' })
    reader.onerror = () => reject(new Error(`读取文件失败: ${file.name}`))
    reader.readAsText(file)
  })
}

async function onFileChange(e) {
  const files = Array.from(e.target.files || [])
  if (!files.length) {
    selectedFiles.value = []
    return
  }
  selectedFiles.value = await Promise.all(files.map(readFile))
}

function conflictKey(entity, change) {
  return `${entity.entity_type}:${entity.entity_name}:${change.field}`
}

function isMergeResolving(entity, change) {
  return !!resolvingMergeKeys[conflictKey(entity, change)]
}

function initializeConflictSelections(doc) {
  Object.keys(conflictSelections).forEach(key => delete conflictSelections[key])
  for (const entity of doc?.diff_result?.entity_diffs || []) {
    if (entity.operation !== 'conflict') continue
    for (const change of entity.field_changes || []) {
      if (change.auto_applicable) continue
      const key = conflictKey(entity, change)
      conflictSelections[key] = conflictSelectionMemory[`${doc?.id}:${key}`] || 'merge'
    }
  }
}

function showDetail(doc) {
  selectedDoc.value = doc
  initializeConflictSelections(doc)
  cancelDraftFieldEdit()
  detailVisible.value = true
}

function openLibraryDetail(item, groupLabel = '') {
  selectedLibraryItem.value = item
  selectedLibraryLabel.value = groupLabel
  libraryDetailVisible.value = true
}

function openSourceSession(sessionId, changeId = '') {
  if (!sessionId) return
  router.push({
    path: '/documents',
    query: {
      tab: 'ai',
      session: sessionId,
      ...(changeId ? { change: changeId } : {}),
    },
  })
}

async function openSettingReviewBatch(row) {
  if (!store.novelId || !row?.id) return
  settingReviewVisible.value = true
  settingReviewLoading.value = true
  selectedSettingReviewBatch.value = null
  selectedSettingReviewChange.value = null
  settingReviewChangeDetailVisible.value = false
  try {
    selectedSettingReviewBatch.value = normalizeSettingReviewBatchPayload(
      await getSettingReviewBatch(store.novelId, row.id)
    )
  } finally {
    settingReviewLoading.value = false
  }
}

function openSettingReviewChangeDetail(change) {
  selectedSettingReviewChange.value = change
  settingReviewChangeDetailVisible.value = true
}

async function applySettingReviewDecision(decision, change = null) {
  const batch = selectedSettingReviewBatch.value
  if (!store.novelId || !batch?.id || settingReviewApplying.value) return
  const targetChanges = change ? [change] : pendingSettingReviewChanges.value
  const decisions = targetChanges
    .filter((item) => item?.status === 'pending')
    .map((item) => ({
      change_id: item.id,
      decision,
    }))
  if (!decisions.length) return
  settingReviewApplying.value = true
  try {
    await applySettingReviewBatch(store.novelId, batch.id, { decisions })
    await Promise.all([store.fetchSettingWorkbench(), store.fetchDocuments(), fetchLibrary()])
    selectedSettingReviewBatch.value = normalizeSettingReviewBatchPayload(
      await getSettingReviewBatch(store.novelId, batch.id)
    )
    if (selectedSettingReviewChange.value) {
      selectedSettingReviewChange.value = (selectedSettingReviewBatch.value?.changes || [])
        .find((item) => item.id === selectedSettingReviewChange.value.id) || selectedSettingReviewChange.value
    }
    ElMessage.success(decision === 'approve' ? 'AI 设定变更已批准' : 'AI 设定变更已拒绝')
  } finally {
    settingReviewApplying.value = false
  }
}

function selectKnowledgeTab(tab) {
  activeKnowledgeTab.value = tab === 'ai' ? 'ai' : 'import'
  const query = { ...route.query }
  if (activeKnowledgeTab.value === 'ai') {
    query.tab = 'ai'
  } else {
    delete query.tab
    delete query.session
    delete query.change
  }
  router.replace({ path: '/documents', query })
}

function openDomainDetail(domain) {
  selectedDomain.value = domain
  domainDetailVisible.value = true
}

function openStyleVersions() {
  styleVersionsVisible.value = true
}

function openLibraryEditor(item, groupLabel = '') {
  libraryEditorTarget.value = {
    id: item.id,
    docType: item.doc_type,
    title: item.title,
    version: item.version,
    groupLabel,
  }
  libraryEditorContent.value = item.content || ''
  libraryEditorError.value = ''
  libraryEditorVisible.value = true
}

function closeLibraryEditor() {
  if (libraryEditorSaving.value) return
  libraryEditorVisible.value = false
  libraryEditorTarget.value = null
  libraryEditorContent.value = ''
  libraryEditorError.value = ''
}

function visibleChanges(entity) {
  return (entity.field_changes || []).filter(change => formatValue(change.new_value))
}

function entityKey(entity) {
  return `${entity.entity_type}:${entity.entity_name}:${entity.operation}`
}

function createDraftFieldKey(entity, change) {
  return `${entity.entity_type}:${entity.entity_name}:${change.field}`
}

function isEditingDraftField(entity, change) {
  return !!editingDraftField.value && editingDraftField.value.key === createDraftFieldKey(entity, change)
}

function isSavingDraftField(entity, change) {
  return savingDraftFieldKey.value === createDraftFieldKey(entity, change)
}

function isMultilineDraftField(field) {
  return multilineDraftFields.has(field)
}

function beginDraftFieldEdit(entity, change) {
  editingDraftField.value = {
    key: createDraftFieldKey(entity, change),
    pendingId: selectedDoc.value?.id || '',
    entityType: entity.entity_type,
    entityName: entity.entity_name,
    field: change.field,
  }
  draftFieldInput.value = normalizeDraftFieldValue(change.new_value)
  draftFieldError.value = ''
}

function cancelDraftFieldEdit() {
  editingDraftField.value = null
  draftFieldInput.value = ''
  draftFieldError.value = ''
  savingDraftFieldKey.value = ''
}

function handleDraftFieldEscape(event) {
  if (!editingDraftField.value || event.key !== 'Escape') return
  event.preventDefault()
  event.stopPropagation()
  cancelDraftFieldEdit()
}

function syncDraftFieldEscapeListener(active) {
  if (active && !draftFieldEscapeListenerAttached) {
    window.addEventListener('keydown', handleDraftFieldEscape, true)
    draftFieldEscapeListenerAttached = true
    return
  }
  if (!active && draftFieldEscapeListenerAttached) {
    window.removeEventListener('keydown', handleDraftFieldEscape, true)
    draftFieldEscapeListenerAttached = false
  }
}

function replacePendingDoc(updatedDoc) {
  const index = (store.pendingDocs || []).findIndex((doc) => doc.id === updatedDoc.id)
  if (index >= 0) {
    store.pendingDocs.splice(index, 1, updatedDoc)
  }
  if (selectedDoc.value?.id === updatedDoc.id) {
    selectedDoc.value = updatedDoc
  }
}

async function saveDraftFieldEdit() {
  if (!editingDraftField.value) return true
  if (!store.novelId || !editingDraftField.value.pendingId) return false
  const payload = editingDraftField.value
  savingDraftFieldKey.value = payload.key
  draftFieldError.value = ''
  try {
    const response = await updatePendingDraftField(store.novelId, payload.pendingId, {
      entity_type: payload.entityType,
      entity_name: payload.entityName,
      field: payload.field,
      value: draftFieldInput.value,
    })
    replacePendingDoc(response.item)
    cancelDraftFieldEdit()
    return true
  } catch (error) {
    draftFieldError.value = error?.response?.data?.detail || error?.message || '保存失败'
    savingDraftFieldKey.value = ''
    return false
  }
}

function buildFieldResolutions() {
  const resolutions = []
  for (const entity of selectedDoc.value?.diff_result?.entity_diffs || []) {
    if (entity.operation !== 'conflict') continue
    for (const change of entity.field_changes || []) {
      if (change.auto_applicable) continue
      const action = conflictSelections[conflictKey(entity, change)]
      if (!action || action === 'keep_old') continue
      resolutions.push({
        entity_type: entity.entity_type,
        entity_name: entity.entity_name,
        field: change.field,
        action,
      })
    }
  }
  return resolutions
}

function rememberConflictSelections(doc) {
  if (!doc?.id) return
  for (const [key, value] of Object.entries(conflictSelections)) {
    conflictSelectionMemory[`${doc.id}:${key}`] = value
  }
}

function clearResolvingMergeKeys() {
  Object.keys(resolvingMergeKeys).forEach(key => delete resolvingMergeKeys[key])
}

function markResolvingMergeKeys(fieldResolutions) {
  clearResolvingMergeKeys()
  for (const resolution of fieldResolutions) {
    if (resolution.action !== 'merge') continue
    resolvingMergeKeys[`${resolution.entity_type}:${resolution.entity_name}:${resolution.field}`] = true
  }
}

function syncSelectedDocFromStore(id) {
  if (!id) return
  const latest = (store.pendingDocs || []).find((doc) => doc.id === id)
  if (latest) {
    selectedDoc.value = latest
    initializeConflictSelections(latest)
    return
  }
  detailVisible.value = false
  selectedDoc.value = null
}

async function fetchLibrary() {
  if (!store.novelId) {
    libraryItems.value = []
    return
  }
  libraryLoading.value = true
  try {
    const library = await getDocumentLibrary(store.novelId)
    libraryItems.value = library.items || []
  } catch {
    libraryItems.value = []
  } finally {
    libraryLoading.value = false
  }
}

async function saveLibraryEditor() {
  if (!store.novelId || !libraryEditorTarget.value) return
  const content = libraryEditorContent.value.trim()
  if (!content) {
    libraryEditorError.value = '内容不能为空'
    return
  }
  libraryEditorSaving.value = true
  libraryEditorError.value = ''
  try {
    await updateLibraryDocument(store.novelId, libraryEditorTarget.value.id, { content })
    await fetchLibrary()
    libraryEditorSaving.value = false
    ElMessage.success(
      libraryEditorTarget.value.docType === 'style_profile'
        ? '文风档案已更新并设为当前版本'
        : '资料已更新为新版本'
    )
    closeLibraryEditor()
  } catch (error) {
    libraryEditorError.value = error?.response?.data?.detail || error?.message || '保存失败'
  } finally {
    libraryEditorSaving.value = false
  }
}

async function upload() {
  if (!selectedFiles.value.length) return
  uploading.value = true
  try {
    const items = selectedFiles.value.map((file) => ({
      ...file,
      ...(knowledgeUsage.value === 'domain'
        ? {
            knowledge_usage: 'domain',
            domain_name: domainName.value.trim() || file.filename.replace(/\.(txt|md)$/i, ''),
            activation_mode: 'auto',
          }
        : {}),
    }))
    uploadSummary.value = await uploadDocumentsBatch(store.novelId, items, 3)
    const accepted = uploadSummary.value.accepted ?? uploadSummary.value.succeeded ?? 0
    ElMessage.success(`导入任务已提交：${accepted} 个`)
    await Promise.all([store.fetchDocuments(), fetchLibrary(), fetchKnowledgeDomains()])
  } finally {
    uploading.value = false
    selectedFiles.value = []
    if (fileInput.value) fileInput.value.value = ''
  }
}

function domainStatusLabel(status) {
  const labels = {
    draft: '草稿',
    unbound: '未绑定',
    suggested: '建议绑定',
    confirmed: '已确认',
    used: '已使用',
    revised: '已编辑',
    disabled: '已禁用',
  }
  return labels[status] || status || '未绑定'
}

function activationModeLabel(mode) {
  const labels = {
    auto: '自动激活',
    manual: '手动激活',
    always: '全局生效',
    disabled: '禁用',
  }
  return labels[mode] || mode || '自动激活'
}

function scopeLabel(scope) {
  if (!scope?.scope_ref) return ''
  if (scope.scope_type === 'volume') return `${scope.scope_ref.replace(/^vol_/, '第')}卷`
  return scope.scope_ref
}

function scopeSummary(scopes = []) {
  return scopes.map(scopeLabel).filter(Boolean).join('、')
}

function firstSuggestedVolume(domain) {
  const scope = (domain.suggested_scopes || []).find((item) => item.scope_type === 'volume')
  return scopeLabel(scope)
}

function domainKeywordSummary(domain) {
  const keywords = domain.activation_keywords || []
  if (!keywords.length) return '未设置'
  const suffix = keywords.length > 4 ? ` 等 ${keywords.length} 个` : ''
  return `${keywords.slice(0, 4).join('、')}${suffix}`
}

async function confirmSuggestedDomain(domain) {
  const scope = (domain.suggested_scopes || []).find((item) => item.scope_type === 'volume')
  if (!scope) return
  await store.confirmKnowledgeDomainScope(domain.id, [scope.scope_ref], 'volume')
  ElMessage.success('规则域绑定已确认')
}

async function disableDomain(domain) {
  await store.disableKnowledgeDomain(domain.id)
  ElMessage.success('规则域已禁用')
}

async function deleteDomain(domain) {
  if (!store.novelId || deletingDomainId.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除规则域“${domain.name}”吗？这会删除该规则域写入的局部文档和局部实体，无法撤销。`,
      '删除规则域',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return
  }
  deletingDomainId.value = domain.id
  try {
    const result = await store.deleteKnowledgeDomain(domain.id)
    await Promise.all([store.fetchDocuments(), fetchLibrary()])
    const deletedDocuments = result?.deleted_documents ?? 0
    const deletedEntities = result?.deleted_entities ?? 0
    ElMessage.success(`规则域已删除，已清理 ${deletedDocuments} 份局部文档、${deletedEntities} 个局部实体`)
  } finally {
    deletingDomainId.value = ''
  }
}

function domainRuleSummary(domain) {
  const rules = domain.rules || {}
  const forbidden = rules.forbidden_now || []
  const foreshadow = rules.foreshadow_only || []
  if (forbidden.length) return `禁止：${summarizeContent(forbidden.slice(0, 2).join('；'), 42)}`
  if (foreshadow.length) return `只能伏笔：${summarizeContent(foreshadow.slice(0, 2).join('；'), 42)}`
  return ''
}

async function approve(id) {
  if (approvingPendingId.value) return
  approvingPendingId.value = id
  try {
    if (selectedDoc.value?.id === id) {
      const draftSaved = await saveDraftFieldEdit()
      if (!draftSaved) return
    }

    rememberConflictSelections(selectedDoc.value)
    const fieldResolutions = selectedDoc.value?.id === id ? buildFieldResolutions() : []
    const hasMergeResolution = fieldResolutions.some((resolution) => resolution.action === 'merge')
    if (selectedDoc.value?.id === id) {
      markResolvingMergeKeys(fieldResolutions)
    }
    await approvePending(store.novelId, id, fieldResolutions)
    await Promise.all([store.fetchDocuments(), fetchLibrary()])
    syncSelectedDocFromStore(id)
    ElMessage.success(hasMergeResolution ? '自动合并完成' : '已批准')
  } finally {
    clearResolvingMergeKeys()
    approvingPendingId.value = ''
  }
}

async function reject(id) {
  if (rejectingPendingId.value) return
  rejectingPendingId.value = id
  try {
    await rejectPending(store.novelId, id)
    ElMessage.success('已拒绝并丢弃该记录')
    clearResolvingMergeKeys()
    if (selectedDoc.value?.id === id) {
      detailVisible.value = false
      selectedDoc.value = null
    }
    await Promise.all([store.fetchDocuments(), fetchLibrary()])
  } finally {
    rejectingPendingId.value = ''
  }
}

async function removeFailedRecord(id) {
  if (deletingPendingId.value) return
  deletingPendingId.value = id
  try {
    await deletePendingDoc(store.novelId, id)
    ElMessage.success('已删除失败记录')
    clearResolvingMergeKeys()
    if (selectedDoc.value?.id === id) {
      detailVisible.value = false
      selectedDoc.value = null
    }
    await Promise.all([store.fetchDocuments(), fetchLibrary()])
  } finally {
    deletingPendingId.value = ''
  }
}

async function cancelProcessingRecord(id) {
  if (deletingPendingId.value) return
  deletingPendingId.value = id
  try {
    await deletePendingDoc(store.novelId, id)
    ElMessage.success('已取消导入')
    if (selectedDoc.value?.id === id) {
      detailVisible.value = false
      selectedDoc.value = null
    }
    await store.fetchDocuments()
  } finally {
    deletingPendingId.value = ''
  }
}

async function activateStyleVersion(version) {
  if (!store.novelId || rollingBackVersion.value) return
  rollingBackVersion.value = version
  try {
    await rollbackStyleProfile(store.novelId, version)
    await fetchLibrary()
    ElMessage.success(`已切换到文风版本 v${version}`)
  } finally {
    rollingBackVersion.value = null
  }
}

function fetchIfReady() {
  if (!store.novelId) {
    libraryItems.value = []
    store.knowledgeDomains = []
    return
  }
  store.fetchDocuments()
  store.fetchSettingWorkbench()
  fetchLibrary()
  fetchKnowledgeDomains()
}

async function fetchKnowledgeDomains() {
  if (!store.novelId) return
  knowledgeDomainsLoading.value = true
  try {
    await store.fetchKnowledgeDomains(true)
  } finally {
    knowledgeDomainsLoading.value = false
  }
}

function stopDocumentPolling() {
  if (documentPollTimer.value) {
    window.clearInterval(documentPollTimer.value)
    documentPollTimer.value = null
  }
}

function startDocumentPolling() {
  if (documentPollTimer.value || !store.novelId) return
  documentPollTimer.value = window.setInterval(() => {
    store.fetchDocuments()
  }, DOCUMENT_POLL_INTERVAL_MS)
}

onMounted(fetchIfReady)
onBeforeUnmount(() => {
  stopDocumentPolling()
  syncDraftFieldEscapeListener(false)
})
watch(() => route.query?.tab, (tab) => {
  activeKnowledgeTab.value = tab === 'ai' ? 'ai' : 'import'
}, { immediate: true })
watch(() => store.novelId, () => {
  stopDocumentPolling()
  uploadSummary.value = null
  fetchIfReady()
})
watch(hasProcessingDocs, (processing) => {
  if (processing) {
    startDocumentPolling()
    return
  }
  stopDocumentPolling()
}, { immediate: true })

watch(conflictSelections, () => {
  rememberConflictSelections(selectedDoc.value)
}, { deep: true })

watch(editingDraftField, (value) => {
  syncDraftFieldEscapeListener(Boolean(value))
})
</script>

<style scoped>
.documents-tabs {
  display: inline-flex;
  gap: 0.25rem;
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: var(--app-surface);
  padding: 0.25rem;
}

.documents-tab {
  border: 0;
  border-radius: 0.55rem;
  background: transparent;
  color: var(--app-text-muted);
  font-size: 0.9rem;
  font-weight: 800;
  padding: 0.58rem 0.9rem;
}

.documents-tab--active {
  background: var(--app-accent);
  color: #fff;
}

.documents-management {
  display: grid;
  gap: 1rem;
}

.documents-management__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
}

.documents-management__title {
  color: var(--app-text);
  font-size: 1.05rem;
  font-weight: 800;
}

.documents-management__description {
  margin-top: 0.35rem;
  max-width: 44rem;
  color: var(--app-text-muted);
  font-size: 0.875rem;
  line-height: 1.6;
}

.documents-management__stats {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
  color: var(--app-text-soft);
  font-size: 0.78rem;
  font-weight: 800;
}

.documents-management__stats span {
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface);
  padding: 0.35rem 0.65rem;
}

.documents-management-grid {
  display: grid;
  align-items: start;
  gap: 1rem;
}

.documents-panel {
  min-width: 0;
}

@media (max-width: 767px) {
  .documents-management__header {
    align-items: flex-start;
    flex-direction: column;
  }

  .documents-management__stats {
    justify-content: flex-start;
  }
}

.documents-pending-table {
  --el-table-border-color: var(--app-border);
  --el-table-border: 1px solid var(--app-border);
  --el-table-header-bg-color: var(--app-surface-soft);
  --el-table-tr-bg-color: transparent;
  --el-table-row-hover-bg-color: var(--app-surface-soft);
  --el-table-bg-color: transparent;
  --el-table-expanded-cell-bg-color: transparent;
  --el-table-header-text-color: var(--app-text-soft);
  --el-table-text-color: var(--app-text);
  --el-fill-color-lighter: var(--app-surface-soft);
  --el-fill-color-blank: transparent;
  border-radius: 1.1rem;
  overflow: hidden;
}

.documents-import-mode {
  display: flex;
  min-height: 5.25rem;
  flex-direction: column;
  gap: 0.45rem;
  border-radius: 1rem;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  padding: 0.95rem 1rem;
  text-align: left;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.documents-import-mode:hover {
  transform: translateY(-1px);
  border-color: rgba(20, 184, 166, 0.6);
}

.documents-import-mode--active {
  border-color: rgba(20, 184, 166, 0.85);
  box-shadow: 0 0 0 3px rgba(20, 184, 166, 0.14);
}

.documents-import-mode__title {
  font-weight: 800;
  color: var(--app-text);
}

.documents-import-mode__desc {
  font-size: 0.82rem;
  line-height: 1.45;
  color: var(--app-text-soft);
}

.documents-pending-table :deep(.el-table__inner-wrapper::before),
.documents-pending-table :deep(.el-table::before) {
  display: none;
}

.documents-pending-table :deep(th.el-table__cell) {
  font-weight: 700;
  background: var(--app-surface-soft);
}

.documents-pending-table :deep(td.el-table__cell),
.documents-pending-table :deep(tr) {
  background: transparent;
}

.documents-pending-table__action {
  --el-button-bg-color: color-mix(in srgb, var(--app-surface-soft) 88%, transparent);
  --el-button-border-color: var(--app-border);
  --el-button-text-color: var(--app-text);
  --el-button-hover-bg-color: var(--app-surface);
  --el-button-hover-border-color: var(--app-border-strong);
  --el-button-hover-text-color: var(--app-text);
}

.documents-pending-table__actions {
  justify-content: flex-end;
  padding-right: 0.75rem;
  box-sizing: border-box;
}

.documents-setting-review-change {
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: var(--app-surface-soft);
  padding: 0.9rem;
}

.documents-setting-review-detail-section {
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: var(--app-surface-soft);
  padding: 0.9rem;
}

.documents-setting-review-detail-section h4 {
  margin: 0 0 0.65rem;
  color: var(--app-text);
  font-size: 0.88rem;
  font-weight: 800;
}

.documents-setting-review-detail-section pre {
  margin: 0;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--app-text-muted);
  font-size: 0.82rem;
  line-height: 1.65;
}

.documents-setting-review-detail-fields {
  display: grid;
  gap: 0.75rem;
  margin: 0;
}

.documents-setting-review-detail-field {
  display: grid;
  grid-template-columns: minmax(5rem, 8rem) minmax(0, 1fr);
  gap: 0.75rem;
}

.documents-setting-review-detail-field dt {
  color: var(--app-text-soft);
  font-size: 0.78rem;
  font-weight: 800;
}

.documents-setting-review-detail-field dd {
  margin: 0;
  min-width: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--app-text);
  font-size: 0.9rem;
  line-height: 1.75;
}

.documents-detail-table {
  --el-table-border-color: var(--app-border);
  --el-table-border: 1px solid var(--app-border);
  --el-table-header-bg-color: color-mix(in srgb, var(--app-surface-soft) 94%, transparent);
  --el-table-tr-bg-color: transparent;
  --el-table-row-hover-bg-color: var(--app-surface-soft);
  --el-table-bg-color: transparent;
  --el-table-expanded-cell-bg-color: transparent;
  --el-table-header-text-color: var(--app-text-soft);
  --el-table-text-color: var(--app-text);
  --el-fill-color-lighter: var(--app-surface-soft);
  --el-fill-color-blank: transparent;
  border-radius: 0.9rem;
  overflow: hidden;
}

.documents-detail-table :deep(.el-table__inner-wrapper::before),
.documents-detail-table :deep(.el-table::before) {
  display: none;
}

.documents-detail-table :deep(th.el-table__cell) {
  font-weight: 700;
  background: color-mix(in srgb, var(--app-surface-soft) 94%, transparent);
}

.documents-detail-table :deep(td.el-table__cell),
.documents-detail-table :deep(tr) {
  background: transparent;
}

.documents-library-card__edit {
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--app-surface-soft) 78%, transparent);
  color: var(--app-text-muted);
  padding: 0.28rem 0.7rem;
  font-size: 0.75rem;
  line-height: 1;
  transition: border-color 0.18s ease, background-color 0.18s ease, color 0.18s ease;
}

.documents-library-card__edit:hover {
  border-color: var(--app-border-strong);
  background: var(--app-surface);
  color: var(--app-text);
}

.documents-ai-badge {
  margin-left: 0.5rem;
  border: 1px solid color-mix(in srgb, #2563eb 35%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, #2563eb 9%, var(--app-surface));
  color: #2563eb;
  padding: 0.05rem 0.45rem;
  font-size: 0.68rem;
  font-weight: 800;
}

.documents-library-editor__textarea {
  width: 100%;
  min-height: 22rem;
  resize: vertical;
  border: 1px solid var(--app-border);
  border-radius: 1rem;
  background: var(--app-surface);
  color: var(--app-text);
  padding: 0.9rem 1rem;
  font-size: 0.95rem;
  line-height: 1.7;
}

.documents-detail-collapse {
  --el-collapse-border-color: var(--app-border);
  --el-collapse-header-bg-color: var(--app-surface-soft);
  --el-collapse-content-bg-color: transparent;
  border-top: 1px solid var(--app-border);
  border-bottom: 1px solid var(--app-border);
  border-radius: 1rem;
  overflow: hidden;
}

.documents-detail-collapse :deep(.el-collapse-item__header) {
  padding: 0.95rem 1rem;
  background: var(--app-surface-soft);
  color: var(--app-text);
  border-bottom: 1px solid var(--app-border);
}

.documents-detail-collapse :deep(.el-collapse-item__wrap),
.documents-detail-collapse :deep(.el-collapse-item__content) {
  background: transparent;
  color: var(--app-text-muted);
  border-bottom: none;
}

.documents-detail-collapse__panel {
  background: transparent;
}

.documents-detail-collapse__content {
  color: var(--app-text-muted);
}

.documents-draft-field__edit {
  opacity: 0;
  border: 1px solid var(--app-border);
  border-radius: 0.75rem;
  background: color-mix(in srgb, var(--app-surface-soft) 72%, transparent);
  color: var(--app-text-muted);
  inline-size: 2rem;
  block-size: 2rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  transition: opacity 0.18s ease, border-color 0.18s ease, background-color 0.18s ease, color 0.18s ease;
}

.documents-draft-field:hover .documents-draft-field__edit,
.documents-draft-field:focus-within .documents-draft-field__edit {
  opacity: 1;
}

.documents-draft-field__edit:hover {
  border-color: var(--app-border-strong);
  background: var(--app-surface);
  color: var(--app-text);
}

.documents-draft-field__edit-icon {
  width: 0.95rem;
  height: 0.95rem;
}

.documents-draft-field__input {
  width: 100%;
  border: 1px solid var(--app-border);
  border-radius: 0.8rem;
  background: var(--app-surface);
  color: var(--app-text);
  padding: 0.65rem 0.8rem;
  font-size: 0.875rem;
  line-height: 1.5;
}

.documents-draft-field__input--textarea {
  min-height: 7rem;
  resize: vertical;
}
</style>
