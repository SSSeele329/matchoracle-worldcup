INTERNAL_TEST_BOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MatchOracle Internal Test Board</title>
  <script src="https://unpkg.com/lucide@0.468.0/dist/umd/lucide.min.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #080b0f;
      --bg-soft: #0d1218;
      --surface: #111820;
      --surface-2: #151f2a;
      --line: #263240;
      --line-soft: rgba(255,255,255,.08);
      --ink: #eef5f9;
      --muted: #92a1ad;
      --muted-2: #657684;
      --accent: #46d5b3;
      --accent-2: #7ab7ff;
      --good: #55d68b;
      --warn: #ffbf5f;
      --bad: #ff6b6b;
      --shadow: 0 24px 70px rgba(0, 0, 0, .36);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100svh;
      background:
        linear-gradient(120deg, rgba(70, 213, 179, .12), transparent 30%),
        radial-gradient(circle at 78% 8%, rgba(122, 183, 255, .16), transparent 34%),
        var(--bg);
      color: var(--ink);
    }
    button, input, select, textarea {
      font: inherit;
    }
    button {
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--ink);
      border-radius: 8px;
      min-height: 38px;
      padding: 8px 12px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      transition: transform .16s ease, border-color .16s ease, background .16s ease;
    }
    button:hover { transform: translateY(-1px); border-color: rgba(70, 213, 179, .55); }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #04110d;
      font-weight: 750;
    }
    button.ghost { background: transparent; }
    button.icon { width: 38px; justify-content: center; padding: 0; }
    .app-shell {
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
      min-height: 100svh;
    }
    .rail {
      border-right: 1px solid var(--line-soft);
      background: rgba(8, 11, 15, .74);
      backdrop-filter: blur(22px);
      padding: 22px 16px;
      position: sticky;
      top: 0;
      height: 100svh;
    }
    .brand {
      display: grid;
      gap: 3px;
      margin-bottom: 26px;
    }
    .brand strong { font-size: 21px; letter-spacing: 0; }
    .brand span { color: var(--muted); font-size: 13px; }
    .nav {
      display: grid;
      gap: 6px;
    }
    .nav button {
      justify-content: flex-start;
      width: 100%;
      background: transparent;
      color: var(--muted);
      border-color: transparent;
    }
    .nav button.active {
      color: var(--ink);
      background: rgba(70, 213, 179, .12);
      border-color: rgba(70, 213, 179, .26);
    }
    .rail-footer {
      position: absolute;
      left: 16px;
      right: 16px;
      bottom: 18px;
      color: var(--muted-2);
      font-size: 12px;
      line-height: 1.45;
    }
    .workspace {
      min-width: 0;
      padding: 22px clamp(18px, 3vw, 42px) 48px;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 24px;
    }
    .topbar h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 48px);
      line-height: .95;
      letter-spacing: 0;
    }
    .topbar p {
      margin: 8px 0 0;
      color: var(--muted);
      max-width: 760px;
      line-height: 1.5;
    }
    .status-strip {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 30px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      color: var(--muted);
      background: rgba(255,255,255,.03);
      font-size: 13px;
      white-space: nowrap;
    }
    .chip.good { color: var(--good); border-color: rgba(85,214,139,.45); }
    .chip.warn { color: var(--warn); border-color: rgba(255,191,95,.48); }
    .chip.bad { color: var(--bad); border-color: rgba(255,107,107,.48); }
    .section {
      display: none;
      animation: rise .22s ease both;
    }
    .section.active { display: block; }
    @keyframes rise {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .band {
      border-top: 1px solid var(--line-soft);
      padding: 22px 0;
    }
    .band:first-child { border-top: 0; }
    .section-title {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 14px;
    }
    .section-title h2 {
      margin: 0;
      font-size: 22px;
      letter-spacing: 0;
    }
    .section-title p {
      margin: 6px 0 0;
      color: var(--muted);
      line-height: 1.45;
    }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 1px;
      border: 1px solid var(--line);
      background: var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .metric {
      background: rgba(17, 24, 32, .94);
      padding: 16px;
      min-width: 0;
    }
    .metric strong {
      display: block;
      font-size: clamp(18px, 2vw, 25px);
      line-height: 1;
      white-space: normal;
      overflow-wrap: anywhere;
    }
    .metric span {
      display: block;
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    .split {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(360px, .9fr);
      gap: 24px;
      align-items: start;
    }
    .split > *, .form-grid > *, .metrics > * {
      min-width: 0;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .form-grid.three {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      min-width: 0;
    }
    input, select, textarea {
      width: 100%;
      min-width: 0;
      border: 1px solid var(--line);
      background: rgba(7, 10, 14, .8);
      color: var(--ink);
      border-radius: 8px;
      padding: 10px 11px;
      outline: none;
    }
    input:focus, select:focus, textarea:focus {
      border-color: rgba(70,213,179,.68);
      box-shadow: 0 0 0 3px rgba(70,213,179,.1);
    }
    textarea {
      min-height: 132px;
      resize: vertical;
      line-height: 1.45;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
    }
    .panel {
      min-width: 0;
      border: 1px solid var(--line);
      background: rgba(17, 24, 32, .78);
      border-radius: 8px;
      padding: 16px;
      box-shadow: var(--shadow);
    }
    .panel h3 {
      margin: 0 0 12px;
      font-size: 15px;
      letter-spacing: .04em;
      text-transform: uppercase;
      color: var(--muted);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      text-align: left;
      border-bottom: 1px solid var(--line-soft);
      padding: 9px 8px;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-weight: 650;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .05em;
    }
    td {
      color: #d9e4eb;
    }
    pre {
      margin: 0;
      white-space: pre-wrap;
      overflow: auto;
      max-height: 420px;
      border: 1px solid var(--line);
      background: #06090d;
      border-radius: 8px;
      padding: 12px;
      color: #c7f7e9;
      font-size: 12px;
      line-height: 1.45;
    }
    .result-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .prob-row {
      display: grid;
      grid-template-columns: 88px 1fr 58px;
      align-items: center;
      gap: 10px;
      margin: 10px 0;
      color: var(--muted);
      font-size: 13px;
    }
    .track {
      height: 10px;
      background: #24313d;
      border-radius: 999px;
      overflow: hidden;
    }
    .track span {
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
    }
    .notice {
      border-left: 3px solid var(--accent);
      background: rgba(70, 213, 179, .08);
      padding: 12px 14px;
      color: var(--muted);
      border-radius: 0 8px 8px 0;
      line-height: 1.5;
    }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .muted { color: var(--muted); }
    .good-text { color: var(--good); }
    .warn-text { color: var(--warn); }
    .bad-text { color: var(--bad); }
    @media (max-width: 980px) {
      .app-shell { grid-template-columns: 1fr; }
      .rail {
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--line-soft);
      }
      .rail-footer { position: static; margin-top: 18px; }
      .nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .topbar { align-items: flex-start; flex-direction: column; }
      .status-strip { justify-content: flex-start; }
      .split, .result-grid { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .form-grid, .form-grid.three { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      .workspace { padding: 18px 14px 38px; }
      .metrics { grid-template-columns: 1fr; }
      .nav { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <aside class="rail">
      <div class="brand">
        <strong>MatchOracle</strong>
        <span>Internal Test Board</span>
      </div>
      <nav class="nav" aria-label="Internal board navigation">
        <button class="active" data-view="overview"><i data-lucide="activity"></i>总览</button>
        <button data-view="predict"><i data-lucide="target"></i>单场预测</button>
        <button data-view="data"><i data-lucide="database-zap"></i>数据管线</button>
        <button data-view="odds"><i data-lucide="line-chart"></i>赔率</button>
        <button data-view="jobs"><i data-lucide="workflow"></i>Worker</button>
        <button data-view="snapshots"><i data-lucide="archive"></i>快照</button>
        <button data-view="calibration"><i data-lucide="scale"></i>校准</button>
      </nav>
      <div class="rail-footer">
        Research and entertainment only. No betting, wagering, financial advice, profit promise, or outcome guarantee.
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <div>
          <h1>Internal Test Board</h1>
          <p>上线前用这个页面跑全链路：模型预测、爆冷风险、赔率、数据同步、worker、快照、校准报告。</p>
        </div>
        <div class="status-strip" id="topStatus">
          <span class="chip warn"><i data-lucide="loader"></i>等待检查</span>
        </div>
      </header>

      <section class="section active" id="view-overview">
        <div class="band">
          <div class="section-title">
            <div>
              <h2>运行状态</h2>
              <p>这里用真实 API 检查当前服务、生产 readiness、后台队列和存储输出。</p>
            </div>
            <div class="actions">
              <button class="primary" onclick="loadOverview()"><i data-lucide="refresh-cw"></i>刷新</button>
            </div>
          </div>
          <div class="metrics" id="overviewMetrics"></div>
        </div>
        <div class="band">
          <div class="split">
            <div class="panel">
              <h3>Readiness checks</h3>
              <div id="readinessTable"></div>
            </div>
            <div class="panel">
              <h3>上线缺口</h3>
              <div id="launchGaps"></div>
            </div>
          </div>
        </div>
      </section>

      <section class="section" id="view-predict">
        <div class="band">
          <div class="section-title">
            <div>
              <h2>单场预测工作台</h2>
              <p>覆盖胜平负、比分、Canonical Probability、爆冷风险、数据可靠性、赔率分歧和 T-60 首发校验。</p>
            </div>
            <div class="actions">
              <button onclick="loadScenario('final')"><i data-lucide="trophy"></i>决赛样例</button>
              <button onclick="loadScenario('upset')"><i data-lucide="zap"></i>爆冷样例</button>
              <button class="primary" onclick="runPrediction()"><i data-lucide="play"></i>运行预测</button>
            </div>
          </div>
          <div class="split">
            <div class="panel">
              <h3>Match input</h3>
              <div class="form-grid">
                <label>主队 <input id="homeTeam" value="Argentina"></label>
                <label>客队 <input id="awayTeam" value="France"></label>
                <label>阶段
                  <select id="stage">
                    <option value="GROUP_STAGE">GROUP_STAGE</option>
                    <option value="ROUND_OF_32">ROUND_OF_32</option>
                    <option value="ROUND_OF_16">ROUND_OF_16</option>
                    <option value="QUARTER_FINAL">QUARTER_FINAL</option>
                    <option value="SEMI_FINAL">SEMI_FINAL</option>
                    <option value="FINAL" selected>FINAL</option>
                  </select>
                </label>
                <label>场馆 <input id="venue" value="MetLife Stadium"></label>
                <label>主队 FIFA 排名 <input id="homeRank" type="number" value="3"></label>
                <label>客队 FIFA 排名 <input id="awayRank" type="number" value="4"></label>
                <label>主队场均进球 <input id="homeGoalsAvg" type="number" step="0.1" value="1.8"></label>
                <label>客队场均进球 <input id="awayGoalsAvg" type="number" step="0.1" value="1.7"></label>
                <label>主队 xGA/场均失球 <input id="homeXga" type="number" step="0.1" value="0.9"></label>
                <label>客队 xGA/场均失球 <input id="awayXga" type="number" step="0.1" value="1.0"></label>
                <label>主队定位球占比 <input id="homeSetpiece" type="number" step="0.01" value="0.25"></label>
                <label>客队定位球占比 <input id="awaySetpiece" type="number" step="0.01" value="0.25"></label>
              </div>
              <div class="form-grid three" style="margin-top:12px;">
                <label>主胜赔率 <input id="homeOdds" type="number" step="0.01" value=""></label>
                <label>平局赔率 <input id="drawOdds" type="number" step="0.01" value=""></label>
                <label>客胜赔率 <input id="awayOdds" type="number" step="0.01" value=""></label>
                <label>开盘主胜 <input id="openingHomeOdds" type="number" step="0.01" value=""></label>
                <label>开盘平局 <input id="openingDrawOdds" type="number" step="0.01" value=""></label>
                <label>开盘客胜 <input id="openingAwayOdds" type="number" step="0.01" value=""></label>
              </div>
              <div class="form-grid" style="margin-top:12px;">
                <label>赛制/爆冷上下文 JSON
                  <textarea id="matchContextJson"></textarea>
                </label>
                <label>T-60 首发 JSON
                  <textarea id="lineupJson"></textarea>
                </label>
              </div>
            </div>
            <div class="panel">
              <h3>Prediction output</h3>
              <div id="predictionOutput" class="notice">还没有运行预测。</div>
            </div>
          </div>
        </div>
      </section>

      <section class="section" id="view-data">
        <div class="band">
          <div class="section-title">
            <div>
              <h2>数据管线</h2>
              <p>Structured facts、F05 Monte Carlo 和 provider 同步都在这里排队，worker 负责真正写入。</p>
            </div>
          </div>
          <div class="split">
            <div class="panel">
              <h3>Structured facts sync</h3>
              <div class="form-grid">
                <label>Worker token <input id="dataWorkerToken" type="password" placeholder="本地无 token 时可留空"></label>
                <label>Match ID <input id="structuredMatchId" value="football-data-org:1"></label>
                <label>Snapshot time <input id="structuredSnapshotTime"></label>
                <label>模式
                  <select id="structuredDryRun">
                    <option value="true">dry-run</option>
                    <option value="false">ingest</option>
                  </select>
                </label>
              </div>
              <div class="actions" style="margin-top:12px;">
                <button class="primary" onclick="queueStructuredFactsSync()"><i data-lucide="send"></i>排队同步</button>
              </div>
              <pre id="structuredOutput" style="margin-top:12px;"></pre>
            </div>
            <div class="panel">
              <h3>F05 Monte Carlo</h3>
              <textarea id="f05Payload"></textarea>
              <div class="actions" style="margin-top:12px;">
                <button onclick="fillF05Sample()"><i data-lucide="file-input"></i>填入样例</button>
                <button class="primary" onclick="queueF05()"><i data-lucide="send"></i>排队模拟</button>
              </div>
              <pre id="f05Output" style="margin-top:12px;"></pre>
            </div>
          </div>
        </div>
      </section>

      <section class="section" id="view-odds">
        <div class="band">
          <div class="section-title">
            <div>
              <h2>赔率快照</h2>
              <p>导入 CSV 后由 worker 写入 market odds store，预测页可手动填赔率或后续接自动 adapter。</p>
            </div>
            <div class="actions">
              <button onclick="loadOddsSnapshots()"><i data-lucide="refresh-cw"></i>刷新快照</button>
            </div>
          </div>
          <div class="split">
            <div class="panel">
              <h3>CSV import</h3>
              <div class="form-grid">
                <label>Worker token <input id="oddsWorkerToken" type="password" placeholder="本地无 token 时可留空"></label>
                <label>Source name <input id="oddsSourceName" value="internal-test-board"></label>
              </div>
              <textarea id="oddsCsv" style="margin-top:12px;">year,date,home_team,away_team,home_odds,draw_odds,away_odds,snapshot_time,source
2026,2026-06-12T20:00:00+00:00,Argentina,France,2.35,3.10,2.95,2026-06-12T12:00:00+00:00,internal-test-board</textarea>
              <div class="actions" style="margin-top:12px;">
                <button class="primary" onclick="queueOddsImport()"><i data-lucide="upload"></i>导入赔率 CSV</button>
              </div>
              <pre id="oddsImportOutput" style="margin-top:12px;"></pre>
            </div>
            <div class="panel">
              <h3>Market odds snapshots</h3>
              <div id="oddsSnapshots"></div>
            </div>
          </div>
        </div>
      </section>

      <section class="section" id="view-jobs">
        <div class="band">
          <div class="section-title">
            <div>
              <h2>Worker 队列</h2>
              <p>本地测试可以手动跑下一条 job；生产部署会由独立 worker 进程循环消费。</p>
            </div>
            <div class="actions">
              <button onclick="loadJobs()"><i data-lucide="refresh-cw"></i>刷新队列</button>
              <button class="primary" onclick="runNextJob()"><i data-lucide="skip-forward"></i>运行下一条</button>
            </div>
          </div>
          <div class="panel">
            <div class="form-grid three">
              <label>Worker token <input id="jobWorkerToken" type="password" placeholder="本地无 token 时可留空"></label>
              <label>Status filter
                <select id="jobStatus">
                  <option value="">全部</option>
                  <option value="QUEUED">QUEUED</option>
                  <option value="RUNNING">RUNNING</option>
                  <option value="SUCCEEDED">SUCCEEDED</option>
                  <option value="FAILED">FAILED</option>
                </select>
              </label>
              <label>Job type <input id="jobType" placeholder="可留空"></label>
            </div>
            <div id="jobsTable" style="margin-top:14px;"></div>
            <pre id="jobOutput" style="margin-top:12px;"></pre>
          </div>
        </div>
      </section>

      <section class="section" id="view-snapshots">
        <div class="band">
          <div class="section-title">
            <div>
              <h2>预测快照</h2>
              <p>检查 snapshot 保存、last-good fallback、prematch final freeze 和 replay 一致性。</p>
            </div>
            <div class="actions">
              <button onclick="loadSnapshots()"><i data-lucide="refresh-cw"></i>刷新快照</button>
              <button class="primary" onclick="saveCurrentPrediction()"><i data-lucide="save"></i>保存当前预测</button>
            </div>
          </div>
          <div class="panel">
            <div class="form-grid three">
              <label>Match ID <input id="snapshotMatchId" value=""></label>
              <label>Snapshot type
                <select id="snapshotType">
                  <option value="">全部</option>
                  <option value="PREMATCH_DRAFT">PREMATCH_DRAFT</option>
                  <option value="PREMATCH_FINAL">PREMATCH_FINAL</option>
                </select>
              </label>
              <label>Replay snapshot ID <input id="replaySnapshotId" placeholder="点击列表自动填入"></label>
            </div>
            <div class="actions" style="margin-top:12px;">
              <button onclick="loadLatestSnapshot()"><i data-lucide="clock"></i>最新快照</button>
              <button onclick="replaySnapshot()"><i data-lucide="rotate-ccw"></i>Replay</button>
            </div>
            <div id="snapshotsTable" style="margin-top:14px;"></div>
            <pre id="snapshotOutput" style="margin-top:12px;"></pre>
          </div>
        </div>
      </section>

      <section class="section" id="view-calibration">
        <div class="band">
          <div class="section-title">
            <div>
              <h2>校准与回测</h2>
              <p>查看 2022 blind-test、split calibration 和模型偏差提示。</p>
            </div>
            <div class="actions">
              <button class="primary" onclick="loadCalibration('wc2022')"><i data-lucide="bar-chart-3"></i>2022 校准</button>
              <button onclick="loadCalibration('split')"><i data-lucide="git-compare"></i>Split 回测</button>
            </div>
          </div>
          <div class="panel">
            <div id="calibrationOutput" class="notice">请选择校准报告。</div>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script>
    const state = { lastPredictionPayload: null, lastPrediction: null };
    const $ = id => document.getElementById(id);
    const fmt = value => value === undefined || value === null || value === '' ? '-' : value;
    const pct = value => `${Math.round((Number(value) || 0) * 1000) / 10}%`;
    const jsonText = value => JSON.stringify(value, null, 2);

    function tokenHeaders(tokenInputId) {
      const token = $(tokenInputId)?.value.trim();
      return token ? { 'X-MatchOracle-Worker-Token': token } : { 'X-MatchOracle-Worker': '1' };
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        headers: {
          ...(options.body ? { 'Content-Type': 'application/json' } : {}),
          ...(options.headers || {})
        }
      });
      const text = await response.text();
      let payload;
      try { payload = text ? JSON.parse(text) : {}; }
      catch (_error) { payload = { raw: text }; }
      if (!response.ok) {
        const error = new Error(payload.message || payload.error || `HTTP ${response.status}`);
        error.payload = payload;
        error.status = response.status;
        throw error;
      }
      return payload;
    }

    function setOutput(id, payload) {
      $(id).textContent = typeof payload === 'string' ? payload : jsonText(payload);
    }

    function metric(label, value, cls = '') {
      return `<div class="metric"><strong class="${cls}">${fmt(value)}</strong><span>${label}</span></div>`;
    }

    function chip(label, cls = '') {
      return `<span class="chip ${cls}">${label}</span>`;
    }

    function renderTable(rows, columns, empty = '暂无数据') {
      if (!rows || !rows.length) return `<div class="notice">${empty}</div>`;
      return `<table><thead><tr>${columns.map(col => `<th>${col.label}</th>`).join('')}</tr></thead><tbody>${
        rows.map(row => `<tr>${columns.map(col => `<td>${col.render ? col.render(row) : fmt(row[col.key])}</td>`).join('')}</tr>`).join('')
      }</tbody></table>`;
    }

    function activateView(view) {
      document.querySelectorAll('.nav button').forEach(button => button.classList.toggle('active', button.dataset.view === view));
      document.querySelectorAll('.section').forEach(section => section.classList.toggle('active', section.id === `view-${view}`));
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function optionalNumber(id) {
      const value = $(id).value.trim();
      return value === '' ? null : Number(value);
    }

    function parseJsonField(id, fallback) {
      const value = $(id).value.trim();
      if (!value) return fallback;
      return JSON.parse(value);
    }

    function isoPlus(hours) {
      return new Date(Date.now() + hours * 60 * 60 * 1000).toISOString();
    }

    function loadScenario(kind) {
      if (kind === 'upset') {
        $('homeTeam').value = 'Brazil';
        $('awayTeam').value = 'Morocco';
        $('stage').value = 'GROUP_STAGE';
        $('venue').value = 'MetLife Stadium';
        $('homeRank').value = '2';
        $('awayRank').value = '14';
        $('homeGoalsAvg').value = '2.0';
        $('awayGoalsAvg').value = '1.1';
        $('homeXga').value = '0.8';
        $('awayXga').value = '1.3';
        $('homeSetpiece').value = '0.20';
        $('awaySetpiece').value = '0.36';
        $('homeOdds').value = '1.55';
        $('drawOdds').value = '4.10';
        $('awayOdds').value = '7.20';
        $('openingHomeOdds').value = '1.75';
        $('openingDrawOdds').value = '3.75';
        $('openingAwayOdds').value = '5.80';
        $('matchContextJson').value = jsonText({
          groupRound: 3,
          homeQualificationStatus: 'ALREADY_QUALIFIED',
          awayQualificationStatus: 'MUST_WIN',
          homeRotationRisk: 0.52,
          awayMustWinPressure: 0.48,
          homeMotivationScore: 0.4,
          awayMotivationScore: 3.0,
          pathIncentiveRisk: 0.35,
          matchDrawIncentive: 0.22
        });
        $('lineupJson').value = '';
        return;
      }
      $('homeTeam').value = 'Argentina';
      $('awayTeam').value = 'France';
      $('stage').value = 'FINAL';
      $('venue').value = 'MetLife Stadium';
      $('homeRank').value = '3';
      $('awayRank').value = '4';
      $('homeGoalsAvg').value = '1.8';
      $('awayGoalsAvg').value = '1.7';
      $('homeXga').value = '0.9';
      $('awayXga').value = '1.0';
      $('homeSetpiece').value = '0.25';
      $('awaySetpiece').value = '0.25';
      $('homeOdds').value = '';
      $('drawOdds').value = '';
      $('awayOdds').value = '';
      $('openingHomeOdds').value = '';
      $('openingDrawOdds').value = '';
      $('openingAwayOdds').value = '';
      $('matchContextJson').value = '{}';
      $('lineupJson').value = jsonText({
        expectedLineup: {
          homeFormation: '4-3-3',
          awayFormation: '4-2-3-1',
          homeKeyPlayers: [{ name: 'Messi', tier: 'TIER_1', role: 'CREATOR' }],
          awayKeyPlayers: [{ name: 'Mbappe', tier: 'TIER_1', role: 'ATTACKER' }]
        }
      });
    }

    function buildPredictionPayload() {
      const context = parseJsonField('matchContextJson', {});
      const lineup = parseJsonField('lineupJson', {});
      const payload = {
        matchId: `${$('homeTeam').value}-${$('awayTeam').value}`.replaceAll(' ', '-').toLowerCase(),
        match: {
          homeTeam: $('homeTeam').value,
          awayTeam: $('awayTeam').value,
          stage: $('stage').value,
          venue: $('venue').value,
          datetime: isoPlus(6),
          matchday: context.groupRound || context.matchday
        },
        teamData: {
          home: { fifaRank: Number($('homeRank').value) },
          away: { fifaRank: Number($('awayRank').value) }
        },
        goalData: {
          home: { actualGoals_avg: Number($('homeGoalsAvg').value), xGA_avg: Number($('homeXga').value), setpieceRate: Number($('homeSetpiece').value) },
          away: { actualGoals_avg: Number($('awayGoalsAvg').value), xGA_avg: Number($('awayXga').value), setpieceRate: Number($('awaySetpiece').value) }
        },
        matchContext: context,
        ...lineup
      };
      const odds = ['homeOdds', 'drawOdds', 'awayOdds'].map(id => optionalNumber(id));
      if (odds.every(value => value !== null)) payload.decimalOdds = { home: odds[0], draw: odds[1], away: odds[2] };
      const opening = ['openingHomeOdds', 'openingDrawOdds', 'openingAwayOdds'].map(id => optionalNumber(id));
      if (opening.every(value => value !== null)) payload.openingDecimalOdds = { home: opening[0], draw: opening[1], away: opening[2] };
      state.lastPredictionPayload = payload;
      return payload;
    }

    async function runPrediction() {
      try {
        const payload = buildPredictionPayload();
        const result = await api('/api/predict', { method: 'POST', body: JSON.stringify(payload) });
        state.lastPrediction = result;
        renderPredictionResult(result);
      } catch (error) {
        $('predictionOutput').innerHTML = `<pre>${jsonText(error.payload || { error: error.message })}</pre>`;
      }
    }

    function renderPredictionResult(result) {
      if (result.verdict && result.verdict.result === 'ABORTED') {
        $('predictionOutput').innerHTML = `<div class="notice bad-text">${result.verdict.executiveSummary}</div><pre>${jsonText(result)}</pre>`;
        return;
      }
      const p = result.probabilities || {};
      const s = result.scorePrediction || {};
      const risk = result.upsetRisk || {};
      const narrative = result.finalRiskNarrative || {};
      const factors = result.factors || [];
      $('predictionOutput').innerHTML = `
        <div class="metrics">
          ${metric('主胜', pct(p.home))}
          ${metric('平局', pct(p.draw))}
          ${metric('客胜', pct(p.away))}
          ${metric('置信度', `${result.verdict.confidence} · ${result.verdict.confidenceScore}`)}
        </div>
        <div class="result-grid" style="margin-top:16px;">
          <div>
            <div class="prob-row"><span>主胜</span><div class="track"><span style="width:${Math.round((p.home || 0) * 100)}%"></span></div><strong>${pct(p.home)}</strong></div>
            <div class="prob-row"><span>平局</span><div class="track"><span style="width:${Math.round((p.draw || 0) * 100)}%"></span></div><strong>${pct(p.draw)}</strong></div>
            <div class="prob-row"><span>客胜</span><div class="track"><span style="width:${Math.round((p.away || 0) * 100)}%"></span></div><strong>${pct(p.away)}</strong></div>
            <div class="notice" style="margin-top:14px;">${result.verdict.executiveSummary}</div>
          </div>
          <div>
            <table>
              <tbody>
                <tr><td>预测比分</td><td>${s.predicted ? `${s.predicted.home}-${s.predicted.away}` : '-'}</td></tr>
                <tr><td>λ</td><td>${fmt(s.homeLambda)} / ${fmt(s.awayLambda)}</td></tr>
                <tr><td>爆冷风险</td><td>${fmt(risk.upsetRiskLevel)} · ${Math.round((risk.upsetRiskScore || 0) * 100)}</td></tr>
                <tr><td>风险主因</td><td>${fmt(narrative.primaryDriver)}</td></tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="band">
          <div class="section-title"><h2>关键输出</h2></div>
          ${renderTable((s.topScenarios || []).slice(0, 5), [
            { label: '比分', render: row => row.score },
            { label: '概率', render: row => pct(row.probability) },
            { label: '说明', render: row => row.label || '-' }
          ], '暂无比分矩阵')}
        </div>
        <div class="band">
          <div class="section-title"><h2>因子与风险</h2></div>
          ${renderTable(factors, [
            { label: 'ID', key: 'id' },
            { label: '因子', key: 'name' },
            { label: '角色', key: 'role' },
            { label: '影响', key: 'impactScore' },
            { label: '解释', key: 'reasoning' }
          ], '暂无因子')}
        </div>
        <pre>${jsonText({
          canonicalProbability: result.canonicalProbability,
          upsetRisk: result.upsetRisk,
          marketAnalysis: result.marketAnalysis,
          finalLineupCheck: result.finalLineupCheck,
          dataReliability: result.dataReliability,
          predictionSnapshotId: result.predictionSnapshotId
        })}</pre>
      `;
    }

    async function saveCurrentPrediction() {
      try {
        const payload = state.lastPredictionPayload || buildPredictionPayload();
        const result = await api('/api/predict?save=1', { method: 'POST', body: JSON.stringify(payload) });
        setOutput('snapshotOutput', result.savedSnapshot || result);
        await loadSnapshots();
      } catch (error) {
        setOutput('snapshotOutput', error.payload || { error: error.message });
      }
    }

    async function loadOverview() {
      const [health, readiness, jobs, snapshots] = await Promise.allSettled([
        api('/api/health'),
        api('/api/readiness'),
        api('/api/jobs?limit=5'),
        api('/api/snapshots?limit=5')
      ]);
      const readinessPayload = readiness.value || readiness.reason?.payload || {};
      const healthOk = health.status === 'fulfilled' && health.value.ok;
      const ready = Boolean(readinessPayload.releaseReadinessManifest?.readyForProduction || readinessPayload.readyForProduction);
      const status = readinessPayload.status || (ready ? 'READY' : 'CHECK');
      $('topStatus').innerHTML = [
        chip(`Health ${healthOk ? 'OK' : 'FAIL'}`, healthOk ? 'good' : 'bad'),
        chip(`Readiness ${status}`, ready ? 'good' : status === 'BLOCKED' ? 'bad' : 'warn'),
        chip(`Jobs ${(jobs.value?.jobs || []).length}`),
        chip(`Snapshots ${(snapshots.value?.snapshots || []).length}`)
      ].join('');
      $('overviewMetrics').innerHTML = [
        metric('Health', healthOk ? 'OK' : 'FAIL', healthOk ? 'good-text' : 'bad-text'),
        metric('Readiness', status, ready ? 'good-text' : 'warn-text'),
        metric('Blocking', (readinessPayload.blockingChecks || []).length),
        metric('Warnings', (readinessPayload.warningChecks || []).length)
      ].join('');
      const checks = readinessPayload.checks || [];
      $('readinessTable').innerHTML = renderTable(checks, [
        { label: '检查', key: 'name' },
        { label: '状态', render: row => `<span class="${row.status === 'PASS' ? 'good-text' : row.status === 'FAIL' ? 'bad-text' : 'warn-text'}">${row.status}</span>` },
        { label: '说明', key: 'message' }
      ], 'Readiness 暂不可用');
      const gaps = [...(readinessPayload.blockingChecks || []), ...(readinessPayload.warningChecks || [])];
      $('launchGaps').innerHTML = gaps.length
        ? `<table><tbody>${gaps.map(item => `<tr><td>${item}</td></tr>`).join('')}</tbody></table>`
        : '<div class="notice good-text">没有 readiness 缺口。</div>';
      if (window.lucide) lucide.createIcons();
    }

    async function queueStructuredFactsSync() {
      try {
        const payload = {
          matchId: $('structuredMatchId').value.trim(),
          snapshotTime: $('structuredSnapshotTime').value.trim(),
          dryRun: $('structuredDryRun').value === 'true'
        };
        const result = await api('/api/structured-facts/sync', {
          method: 'POST',
          headers: tokenHeaders('dataWorkerToken'),
          body: JSON.stringify(payload)
        });
        setOutput('structuredOutput', result);
        await loadJobs();
      } catch (error) {
        setOutput('structuredOutput', error.payload || { error: error.message });
      }
    }

    function buildF05Sample() {
      const matches = [];
      const probs = { home: 0.36, draw: 0.28, away: 0.36 };
      for (let group = 1; group <= 12; group += 1) {
        const prefix = `G${String(group).padStart(2, '0')}`;
        const teams = [`${prefix} Team 1`, `${prefix} Team 2`, `${prefix} Team 3`, `${prefix} Team 4`];
        const add = (n, home, away, date, actualScore = null, probabilities = null) => {
          const match = { matchId: `${prefix}-M${n}`, stage: 'GROUP_STAGE', group: `Group ${group}`, homeTeam: teams[home], awayTeam: teams[away], date, time: '18:00' };
          if (actualScore) match.actualScore = actualScore;
          if (probabilities) match.probabilities = probabilities;
          matches.push(match);
        };
        add(1, 0, 1, '2026-06-01', { home: 2, away: 0 });
        add(2, 2, 3, '2026-06-01', { home: 1, away: 0 });
        add(3, 0, 2, '2026-06-05', { home: 1, away: 0 });
        add(4, 1, 3, '2026-06-05', { home: 2, away: 0 });
        add(5, 1, 2, '2026-06-09', null, probs);
        add(6, 0, 3, '2026-06-09', null, { home: 0.65, draw: 0.22, away: 0.13 });
      }
      return {
        currentMatchId: 'G01-M5',
        dependencySnapshotLock: { lockType: 'T24_DEPENDENCY', snapshotId: 'internal-t24-lock', lockedAt: '2026-06-08T18:00:00+00:00', source: 'internal-test-board' },
        matches,
        simulations: 50,
        seed: 17
      };
    }

    function fillF05Sample() {
      $('f05Payload').value = jsonText(buildF05Sample());
    }

    async function queueF05() {
      try {
        const result = await api('/api/f05/monte-carlo', {
          method: 'POST',
          headers: tokenHeaders('dataWorkerToken'),
          body: $('f05Payload').value
        });
        setOutput('f05Output', result);
        await loadJobs();
      } catch (error) {
        setOutput('f05Output', error.payload || { error: error.message });
      }
    }

    async function queueOddsImport() {
      try {
        const result = await api('/api/odds/import', {
          method: 'POST',
          headers: tokenHeaders('oddsWorkerToken'),
          body: JSON.stringify({ csvText: $('oddsCsv').value, sourceName: $('oddsSourceName').value })
        });
        setOutput('oddsImportOutput', result);
        await loadJobs();
      } catch (error) {
        setOutput('oddsImportOutput', error.payload || { error: error.message });
      }
    }

    async function loadOddsSnapshots() {
      try {
        const result = await api('/api/odds/snapshots?limit=20');
        $('oddsSnapshots').innerHTML = renderTable(result.snapshots || [], [
          { label: 'Match', render: row => `${row.homeTeam} vs ${row.awayTeam}` },
          { label: 'Kickoff', key: 'kickoffAt' },
          { label: 'Odds', render: row => `${row.decimalOdds.home}/${row.decimalOdds.draw}/${row.decimalOdds.away}` },
          { label: 'Source', key: 'source' }
        ], '暂无赔率快照');
      } catch (error) {
        $('oddsSnapshots').innerHTML = `<pre>${jsonText(error.payload || { error: error.message })}</pre>`;
      }
    }

    async function loadJobs() {
      try {
        const params = new URLSearchParams({ limit: '30' });
        if ($('jobStatus').value) params.set('status', $('jobStatus').value);
        if ($('jobType').value.trim()) params.set('jobType', $('jobType').value.trim());
        const result = await api(`/api/jobs?${params}`);
        $('jobsTable').innerHTML = renderTable(result.jobs || [], [
          { label: 'Job ID', render: row => `<button class="ghost" onclick="loadJobDetail('${row.jobId}')">${row.jobId}</button>` },
          { label: 'Type', key: 'jobType' },
          { label: 'Status', key: 'status' },
          { label: 'Attempts', key: 'attempts' },
          { label: 'Created', key: 'createdAt' }
        ], '暂无后台任务');
        if (window.lucide) lucide.createIcons();
      } catch (error) {
        $('jobsTable').innerHTML = `<pre>${jsonText(error.payload || { error: error.message })}</pre>`;
      }
    }

    async function loadJobDetail(jobId) {
      try {
        const result = await api(`/api/jobs/${jobId}?includePayload=1`, { headers: tokenHeaders('jobWorkerToken') });
        setOutput('jobOutput', result);
      } catch (error) {
        setOutput('jobOutput', error.payload || { error: error.message });
      }
    }

    async function runNextJob() {
      try {
        const result = await api('/api/jobs/run-next', {
          method: 'POST',
          headers: { ...tokenHeaders('jobWorkerToken'), 'X-MatchOracle-Worker-Id': 'internal-test-board' }
        });
        setOutput('jobOutput', result);
        await loadJobs();
        await loadOddsSnapshots();
      } catch (error) {
        setOutput('jobOutput', error.payload || { error: error.message });
      }
    }

    async function loadSnapshots() {
      try {
        const params = new URLSearchParams({ limit: '30' });
        if ($('snapshotMatchId').value.trim()) params.set('matchId', $('snapshotMatchId').value.trim());
        if ($('snapshotType').value) params.set('snapshotType', $('snapshotType').value);
        const result = await api(`/api/snapshots?${params}`);
        $('snapshotsTable').innerHTML = renderTable(result.snapshots || [], [
          { label: 'Snapshot', render: row => `<button class="ghost" onclick="selectSnapshot('${row.predictionSnapshotId}')">${row.predictionSnapshotId}</button>` },
          { label: 'Match', key: 'matchId' },
          { label: 'Type', key: 'snapshotType' },
          { label: 'Saved', key: 'savedAt' },
          { label: 'Freeze', key: 'freezeStatus' }
        ], '暂无预测快照');
        if (window.lucide) lucide.createIcons();
      } catch (error) {
        $('snapshotsTable').innerHTML = `<pre>${jsonText(error.payload || { error: error.message })}</pre>`;
      }
    }

    function selectSnapshot(snapshotId) {
      $('replaySnapshotId').value = snapshotId;
      loadSnapshotById(snapshotId);
    }

    async function loadSnapshotById(snapshotId) {
      try {
        const result = await api(`/api/snapshots/${snapshotId}`);
        setOutput('snapshotOutput', result);
      } catch (error) {
        setOutput('snapshotOutput', error.payload || { error: error.message });
      }
    }

    async function loadLatestSnapshot() {
      try {
        const params = new URLSearchParams();
        if ($('snapshotMatchId').value.trim()) params.set('matchId', $('snapshotMatchId').value.trim());
        if ($('snapshotType').value) params.set('snapshotType', $('snapshotType').value);
        const result = await api(`/api/snapshots/latest?${params}`);
        setOutput('snapshotOutput', result);
        $('replaySnapshotId').value = result.predictionSnapshotId || '';
      } catch (error) {
        setOutput('snapshotOutput', error.payload || { error: error.message });
      }
    }

    async function replaySnapshot() {
      try {
        const id = $('replaySnapshotId').value.trim();
        if (!id) throw new Error('Missing snapshot id');
        const result = await api(`/api/snapshots/${id}/replay`, { method: 'POST' });
        setOutput('snapshotOutput', result);
      } catch (error) {
        setOutput('snapshotOutput', error.payload || { error: error.message });
      }
    }

    async function loadCalibration(kind) {
      try {
        const result = await api(kind === 'split' ? '/api/calibration/split' : '/api/calibration/wc2022');
        const summary = result.summary || result;
        $('calibrationOutput').innerHTML = `
          <div class="metrics">
            ${metric('Matches', summary.matches)}
            ${metric('Accuracy', summary.resultAccuracy !== undefined ? pct(summary.resultAccuracy) : '-')}
            ${metric('Brier', summary.probabilityMetrics?.brierScore || summary.brierScore || '-')}
            ${metric('Log Loss', summary.probabilityMetrics?.logLoss || summary.logLoss || '-')}
          </div>
          <pre style="margin-top:14px;">${jsonText(result)}</pre>
        `;
      } catch (error) {
        $('calibrationOutput').innerHTML = `<pre>${jsonText(error.payload || { error: error.message })}</pre>`;
      }
    }

    function initBoard() {
      document.querySelectorAll('.nav button').forEach(button => {
        button.addEventListener('click', () => activateView(button.dataset.view));
      });
      $('structuredSnapshotTime').value = new Date().toISOString();
      $('matchContextJson').value = '{}';
      $('lineupJson').value = '{}';
      fillF05Sample();
      loadOverview();
      loadJobs();
      loadSnapshots();
      loadOddsSnapshots();
      if (window.lucide) lucide.createIcons();
    }

    document.addEventListener('DOMContentLoaded', initBoard);
  </script>
</body>
</html>
"""
