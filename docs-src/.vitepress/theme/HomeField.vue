<script setup lang="ts">
import { withBase } from 'vitepress'

const route = (path: string) => withBase(path)
</script>

<template>
  <main class="field-home">
    <aside class="field-home__rail" aria-label="首页索引">
      <a class="field-home__rail-mark" :href="route('/')" aria-label="回到 RiyaBot 文档首页">
        <img class="field-home__rail-logo" :src="route('/logo.svg')" alt="" width="40" height="40" />
      </a>

      <div class="field-home__rail-line" aria-hidden="true"></div>

      <nav class="field-home__rail-nav" aria-label="首页章节">
        <a class="field-home__rail-link is-active" href="#field-overview">
          <span class="field-home__rail-index">01</span>
          <span class="field-home__rail-label">概览</span>
        </a>
        <a class="field-home__rail-link" href="#field-system">
          <span class="field-home__rail-index">02</span>
          <span class="field-home__rail-label">系统</span>
        </a>
      </nav>

      <span class="field-home__rail-end">DOCS / 01</span>
    </aside>

    <div class="field-home__content">
      <section id="field-overview" class="field-home__hero" aria-labelledby="field-home-title">
        <div class="field-home__hero-copy">
          <p class="field-kicker"><span>01</span> RIYABOT / DOCUMENTATION SYSTEM</p>
          <h1 id="field-home-title">
            <span class="field-home__hero-lead">让 <b>RiyaBot</b></span>
            <span class="field-home__hero-title">进入你的聊天</span>
          </h1>
          <p class="field-home__intro">
            一个会观察、记忆并作出行动的聊天机器人。用大语言模型、长期记忆、行为规划与插件系统，把一次回复变成持续的互动。
          </p>

          <div class="field-home__hero-actions" aria-label="主要入口">
            <a class="field-action field-action--primary" :href="route('/guide/installation')">
              <span class="field-action__mark" aria-hidden="true">↗</span>
              <span>开始部署</span>
            </a>
            <a class="field-action" :href="route('/plugins/index')">
              <span class="field-action__mark" aria-hidden="true">+</span>
              <span>插件开发</span>
            </a>
          </div>

          <div class="field-home__hero-meta">
            <span>OPEN DOCUMENTATION</span>
            <span>GPL-3.0</span>
            <a href="https://github.com/hsd221/riyabot">VIEW SOURCE ↗</a>
          </div>
        </div>

        <div class="field-home__schematic" aria-label="RiyaBot 系统结构图">
          <div class="field-schematic__header">
            <span>系统结构</span>
            <span>CORE MAP · 消息 → 记忆 → 学习 → 扩展</span>
          </div>
          <div class="field-schematic__canvas">
            <div class="field-schematic__axis field-schematic__axis--horizontal" aria-hidden="true"></div>
            <div class="field-schematic__axis field-schematic__axis--vertical" aria-hidden="true"></div>
            <div class="field-schematic__ring field-schematic__ring--outer" aria-hidden="true"></div>
            <div class="field-schematic__ring field-schematic__ring--inner" aria-hidden="true"></div>
            <div class="field-schematic__core" aria-hidden="true">
              <span>RIYA</span>
              <small>CORE</small>
            </div>

            <a class="field-schematic__node field-schematic__node--chat" :href="route('/guide/architecture')">
              <span class="field-schematic__node-index">01</span>
              <strong>CHAT</strong>
              <small>何时开口，如何回应</small>
            </a>
            <a class="field-schematic__node field-schematic__node--memory" :href="route('/guide/architecture')">
              <span class="field-schematic__node-index">02</span>
              <strong>MEMORY</strong>
              <small>SQLite 持久，向量可选</small>
            </a>
            <a class="field-schematic__node field-schematic__node--learning" :href="route('/guide/architecture')">
              <span class="field-schematic__node-index">03</span>
              <strong>LEARNING</strong>
              <small>从对话中学习表达</small>
            </a>
            <a class="field-schematic__node field-schematic__node--plugins" :href="route('/plugins/index')">
              <span class="field-schematic__node-index">04</span>
              <strong>PLUGINS</strong>
              <small>Tool Call 扩展能力</small>
            </a>
          </div>
          <div class="field-schematic__footer">
            <span class="field-schematic__status"><i aria-hidden="true"></i> DOCUMENTED</span>
          </div>
        </div>

        <div class="field-home__hero-scale" aria-hidden="true">
          <span>R</span>
          <span>0</span>
          <span>1</span>
          <span>2</span>
        </div>
      </section>

      <section id="field-system" class="field-home__system" aria-labelledby="field-system-title">
        <div class="field-system__intro">
          <p class="field-kicker"><span>02</span> SYSTEM FIELD</p>
          <h2 id="field-system-title">一套持续互动的 bot 系统</h2>
          <p>RiyaBot 不会等待命令。它观察上下文、决定何时开口、用长期记忆沉淀关系，并从每次对话中调整自己的表达——把一次回复变成持续的互动。</p>
        </div>
        <div class="field-system__facts" aria-label="项目事实">
          <div class="field-system__fact">
            <span class="field-system__fact-key">RUNTIME</span>
            <strong>Python 3.10+</strong>
            <span>Runner / Worker 双进程</span>
          </div>
          <div class="field-system__fact">
            <span class="field-system__fact-key">MEMORY</span>
            <strong>SQLite + Qdrant</strong>
            <span>SQLite 为事实来源，向量索引可选，不可用时优雅降级</span>
          </div>
          <div class="field-system__fact">
            <span class="field-system__fact-key">EXTENSION</span>
            <strong>Tool Call</strong>
            <span>原生工具调用接入聊天流程</span>
          </div>
          <div class="field-system__fact">
            <span class="field-system__fact-key">LICENSE</span>
            <strong>GPL-3.0</strong>
            <span>fork 自 MaiBot / MaiCore</span>
          </div>
        </div>
      </section>

      <footer class="field-home__footer">
        <span>RIYABOT / FIELD DOCUMENTATION</span>
        <span>READ THE SYSTEM · BUILD YOUR EXTENSION</span>
        <a href="https://github.com/hsd221/riyabot">GITHUB ↗</a>
      </footer>
    </div>
  </main>
</template>
