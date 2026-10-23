CONSUMER_PAGE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MatchOracle World Cup Prediction Center</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07100d;
      --surface: rgba(246, 247, 239, 0.08);
      --surface-strong: rgba(246, 247, 239, 0.13);
      --line: rgba(246, 247, 239, 0.18);
      --ink: #f7f8ef;
      --muted: rgba(247, 248, 239, 0.68);
      --soft: rgba(247, 248, 239, 0.48);
      --accent: #e94f37;
      --field: #1f7a48;
      --field-deep: #0f4f34;
      --gold: #d8b45d;
      --good: #60d394;
      --warn: #f6c85f;
      --bad: #ff4d4d;
      --draw: rgba(247, 248, 239, 0.48);
      --shadow: 0 28px 80px rgba(0, 0, 0, 0.35);
      --radius: 8px;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * {
      box-sizing: border-box;
    }

    html {
      scroll-behavior: smooth;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 18% 12%, rgba(31, 122, 72, 0.34), transparent 34rem),
        radial-gradient(circle at 82% 4%, rgba(233, 79, 55, 0.17), transparent 30rem),
        linear-gradient(135deg, #07100d 0%, #0d1a16 48%, #151510 100%);
      color: var(--ink);
      letter-spacing: 0;
    }

    button {
      border: 0;
      font: inherit;
    }

    a {
      color: inherit;
      text-decoration: none;
    }

    [hidden] {
      display: none !important;
    }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 30;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      min-height: 72px;
      padding: 18px clamp(18px, 4vw, 56px);
      border-bottom: 1px solid rgba(246, 247, 239, 0.12);
      background: rgba(7, 16, 13, 0.76);
      backdrop-filter: blur(18px);
    }

    .brand {
      display: flex;
      align-items: baseline;
      gap: 12px;
      min-width: 0;
    }

    .brand strong {
      font-size: clamp(22px, 3vw, 34px);
      line-height: 1;
      white-space: nowrap;
    }

    .brand span {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.2;
      white-space: nowrap;
    }

    .top-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 13px;
    }

    .icon-button,
    .lang-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      min-height: 38px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(246, 247, 239, 0.06);
      color: var(--ink);
      cursor: pointer;
      transition: transform 160ms ease, background 160ms ease, border-color 160ms ease;
    }

    .icon-button:hover,
    .lang-button:hover {
      transform: translateY(-1px);
      background: rgba(246, 247, 239, 0.11);
      border-color: rgba(246, 247, 239, 0.30);
    }

    svg {
      width: 16px;
      height: 16px;
    }

    main {
      padding: 28px clamp(18px, 4vw, 56px) 48px;
    }

    .app-shell {
      display: grid;
      gap: 20px;
      max-width: 1540px;
      margin: 0 auto;
    }

    .status-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 9px;
      color: var(--muted);
      font-size: 13px;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 28px;
      padding: 0 10px;
      border: 1px solid rgba(246, 247, 239, 0.16);
      border-radius: 999px;
      background: rgba(7, 16, 13, 0.32);
      color: var(--muted);
      white-space: nowrap;
    }

    .pill.hot {
      border-color: rgba(233, 79, 55, 0.50);
      color: #ffd7d0;
      background: rgba(233, 79, 55, 0.16);
    }

    .pill.good {
      border-color: rgba(96, 211, 148, 0.42);
      color: #b8ffd8;
      background: rgba(96, 211, 148, 0.12);
    }

    .workspace {
      display: grid;
      grid-template-columns: minmax(300px, 0.34fr) minmax(0, 1fr);
      gap: 20px;
      align-items: start;
    }

    .fixture-rail {
      position: sticky;
      top: 92px;
      display: grid;
      gap: 14px;
      max-height: calc(100svh - 116px);
      overflow: auto;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(7, 16, 13, 0.58);
      box-shadow: var(--shadow);
      scrollbar-width: thin;
    }

    .section-heading {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 12px;
    }

    .section-heading h2,
    .section-heading h3 {
      margin: 0;
      font-size: 17px;
      line-height: 1.1;
    }

    .section-heading span,
    .section-lead {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }

    .fixture-list {
      display: grid;
      gap: 10px;
    }

    .fixture-card {
      display: grid;
      gap: 9px;
      width: 100%;
      min-height: 108px;
      padding: 13px;
      border: 1px solid rgba(246, 247, 239, 0.10);
      border-radius: var(--radius);
      background: rgba(246, 247, 239, 0.045);
      color: var(--ink);
      text-align: left;
      cursor: pointer;
      transition: transform 160ms ease, background 160ms ease, border-color 160ms ease;
    }

    .fixture-card:hover {
      transform: translateY(-1px);
      border-color: rgba(246, 247, 239, 0.28);
      background: rgba(246, 247, 239, 0.075);
    }

    .fixture-card.active {
      border-color: rgba(233, 79, 55, 0.62);
      background: rgba(233, 79, 55, 0.15);
    }

    .fixture-card-top,
    .fixture-card-mid,
    .fixture-card-foot {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-width: 0;
    }

    .fixture-card-top,
    .fixture-card-foot {
      color: var(--muted);
      font-size: 12px;
    }

    .fixture-card-mid strong {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 15px;
    }

    .fixture-card-mid span {
      flex: 0 0 auto;
      color: var(--soft);
      font-size: 12px;
      font-weight: 700;
    }

    .empty-state {
      display: grid;
      gap: 12px;
      padding: 14px;
      border: 1px solid rgba(233, 79, 55, 0.35);
      border-radius: var(--radius);
      background: rgba(233, 79, 55, 0.10);
    }

    .match-deck {
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(7, 16, 13, 0.58);
      box-shadow: var(--shadow);
    }

    .match-visual {
      position: relative;
      overflow: hidden;
      display: grid;
      gap: 22px;
      min-height: 430px;
      padding: clamp(18px, 3vw, 34px);
      background:
        linear-gradient(90deg, rgba(7, 16, 13, 0.94), rgba(7, 16, 13, 0.62), rgba(7, 16, 13, 0.94)),
        repeating-linear-gradient(90deg, rgba(255,255,255,0.038) 0 1px, transparent 1px 72px),
        linear-gradient(180deg, var(--field) 0%, var(--field-deep) 100%);
      isolation: isolate;
    }

    .match-visual::before {
      content: "";
      position: absolute;
      inset: 48px 11%;
      border: 1px solid rgba(247, 248, 239, 0.16);
      border-radius: 999px;
      z-index: -1;
    }

    .match-visual::after {
      content: "";
      position: absolute;
      inset: 0 50% 0 auto;
      width: 1px;
      background: rgba(247, 248, 239, 0.18);
      z-index: -1;
    }

    .scoreboard {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(210px, 330px) minmax(0, 1fr);
      gap: clamp(18px, 4vw, 40px);
      align-items: center;
    }

    .team {
      display: grid;
      gap: 14px;
      min-width: 0;
    }

    .team.away {
      text-align: right;
      justify-items: end;
    }

    .flag-mark {
      display: grid;
      place-items: center;
      width: clamp(76px, 10vw, 118px);
      aspect-ratio: 1;
      border: 1px solid rgba(247, 248, 239, 0.22);
      border-radius: 50%;
      background: rgba(7, 16, 13, 0.36);
      box-shadow: inset 0 0 0 8px rgba(247, 248, 239, 0.045);
      font-size: clamp(42px, 7vw, 70px);
    }

    .team-name {
      display: grid;
      gap: 8px;
      min-width: 0;
    }

    .team-name h1,
    .team-name h2 {
      margin: 0;
      overflow-wrap: break-word;
      word-break: normal;
      hyphens: none;
      font-size: clamp(32px, 4.8vw, 64px);
      line-height: 0.96;
      letter-spacing: 0;
    }

    .team-name span {
      color: var(--muted);
      font-size: 13px;
    }

    .form-dots {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      vertical-align: middle;
    }

    .form-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      border: 1px solid rgba(255,255,255,0.35);
      box-shadow: 0 0 10px rgba(255,255,255,0.10);
    }

    .form-dot.win {
      background: var(--good);
      box-shadow: 0 0 12px rgba(96, 211, 148, 0.42);
    }

    .form-dot.loss {
      background: var(--bad);
      box-shadow: 0 0 12px rgba(255, 77, 77, 0.42);
    }

    .form-dot.draw {
      background: var(--draw);
    }

    .score-center {
      display: grid;
      justify-items: center;
      gap: 12px;
      min-width: 0;
      text-align: center;
    }

    .score-label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }

    .score {
      display: flex;
      align-items: center;
      gap: clamp(10px, 2vw, 18px);
      font-size: clamp(62px, 10vw, 122px);
      font-weight: 800;
      line-height: 0.9;
    }

    .score span {
      min-width: 0.7em;
      text-align: center;
    }

    .score em {
      color: rgba(247, 248, 239, 0.44);
      font-style: normal;
      font-weight: 500;
    }

    .verdict {
      display: grid;
      gap: 6px;
      max-width: 380px;
    }

    .verdict strong {
      font-size: clamp(18px, 3vw, 27px);
    }

    .verdict span {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }

    .probability-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .probability-lane {
      display: grid;
      gap: 9px;
      min-width: 0;
      padding: 13px;
      border-top: 1px solid rgba(247, 248, 239, 0.22);
      background: rgba(7, 16, 13, 0.22);
    }

    .prob-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }

    .prob-head strong {
      color: var(--ink);
      font-size: 18px;
    }

    .bar {
      overflow: hidden;
      height: 9px;
      border-radius: 999px;
      background: rgba(247, 248, 239, 0.12);
    }

    .bar > i {
      display: block;
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--gold));
      transition: width 700ms cubic-bezier(.2,.8,.2,1);
    }

    .content-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 0.42fr);
      gap: 18px;
      align-items: start;
      padding: 18px;
    }

    .main-stack,
    .side-stack {
      display: grid;
      gap: 18px;
      min-width: 0;
    }

    .panel {
      display: grid;
      gap: 16px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(7, 16, 13, 0.58);
    }

    .signal-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .signal {
      display: grid;
      gap: 8px;
      min-height: 112px;
      padding: 13px;
      border-left: 2px solid rgba(233, 79, 55, 0.72);
      background: rgba(246, 247, 239, 0.055);
    }

    .signal span {
      color: var(--soft);
      font-size: 12px;
      line-height: 1.35;
    }

    .signal strong {
      font-size: clamp(20px, 3vw, 29px);
      line-height: 1;
    }

    .compact-list,
    .factor-list,
    .player-list {
      display: grid;
      gap: 10px;
    }

    .compact-row,
    .factor-row,
    .player {
      display: grid;
      align-items: center;
      gap: 12px;
      min-width: 0;
      min-height: 44px;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(246, 247, 239, 0.10);
      color: var(--muted);
      font-size: 13px;
    }

    .compact-row {
      grid-template-columns: auto minmax(0, 1fr) auto;
    }

    .compact-row:last-child,
    .factor-row:last-child,
    .player:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }

    .compact-row strong,
    .player strong,
    .factor-title strong {
      color: var(--ink);
    }

    .outcome-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent);
    }

    .factor-group {
      display: grid;
      gap: 8px;
    }

    .factor-group + .factor-group,
    details.factor-group {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid rgba(246, 247, 239, 0.10);
    }

    .factor-group-title,
    .factor-group summary {
      color: #ffd7d0;
      font-size: 12px;
      font-weight: 700;
    }

    .factor-group summary {
      display: flex;
      justify-content: space-between;
      cursor: pointer;
      list-style: none;
    }

    .factor-group summary::-webkit-details-marker {
      display: none;
    }

    .factor-row {
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: start;
      padding: 12px 0;
    }

    .factor-title {
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    .factor-title span {
      color: var(--soft);
      line-height: 1.5;
    }

    .factor-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      color: var(--soft);
      font-size: 12px;
    }

    .impact {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 74px;
      min-height: 30px;
      padding: 0 9px;
      border-radius: 999px;
      background: rgba(247, 248, 239, 0.08);
      color: var(--ink);
      font-weight: 700;
      font-size: 12px;
    }

    .impact.home {
      background: rgba(96, 211, 148, 0.16);
      color: #b8ffd8;
    }

    .impact.away {
      background: rgba(246, 200, 95, 0.16);
      color: #ffe1a2;
    }

    .impact.neutral {
      color: var(--muted);
    }

    .players {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }

    .player-side {
      display: grid;
      gap: 12px;
      min-width: 0;
    }

    .player-side header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(247, 248, 239, 0.12);
    }

    .player-side header span {
      color: var(--muted);
      font-size: 12px;
    }

    .player {
      grid-template-columns: minmax(0, 1fr) auto;
      padding: 9px 0;
    }

    .player-name {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .player-name strong,
    .player-name span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .player-name span {
      color: var(--soft);
      font-size: 12px;
    }

    .role {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 38px;
      min-height: 28px;
      padding: 0 8px;
      border-radius: 999px;
      color: var(--ink);
      background: rgba(216, 180, 93, 0.24);
      font-size: 12px;
      font-weight: 700;
    }

    .risk-panel {
      border-color: rgba(233, 79, 55, 0.38);
      background: rgba(233, 79, 55, 0.12);
    }

    .risk-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .risk-level {
      display: inline-flex;
      align-items: center;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 999px;
      background: rgba(233, 79, 55, 0.22);
      color: #ffd7d0;
      font-weight: 700;
    }

    .tag-cloud,
    .source-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .tag {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 9px;
      border: 1px solid rgba(247, 248, 239, 0.15);
      border-radius: 999px;
      color: var(--muted);
      background: rgba(7, 16, 13, 0.28);
      font-size: 12px;
    }

    .fine-print {
      color: var(--soft);
      font-size: 12px;
      line-height: 1.6;
    }

    .loading {
      opacity: 0.58;
      pointer-events: none;
    }

    @media (max-width: 1180px) {
      .workspace,
      .content-grid {
        grid-template-columns: 1fr;
      }

      .fixture-rail {
        position: static;
        max-height: none;
      }

      .fixture-list {
        grid-template-columns: repeat(3, minmax(230px, 1fr));
        overflow-x: auto;
      }

      .scoreboard {
        grid-template-columns: 1fr;
      }

      .team.away {
        text-align: left;
        justify-items: start;
      }

      .score-center {
        order: -1;
      }
    }

    @media (max-width: 820px) {
      .topbar {
        align-items: flex-start;
        flex-direction: column;
      }

      .brand {
        display: grid;
        gap: 6px;
      }

      .brand span {
        white-space: normal;
      }

      .top-actions {
        width: 100%;
        justify-content: space-between;
      }

      main {
        padding: 16px 12px 34px;
      }

      .match-visual {
        min-height: auto;
      }

      .probability-strip,
      .signal-grid,
      .players {
        grid-template-columns: 1fr;
      }

      .content-grid,
      .panel,
      .fixture-rail {
        padding: 14px;
      }

      .fixture-list {
        grid-template-columns: 1fr;
      }

      .team-name h1,
      .team-name h2 {
        font-size: clamp(36px, 12vw, 54px);
      }

      .score {
        font-size: clamp(68px, 20vw, 96px);
      }

      .factor-row {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand">
      <strong>MatchOracle</strong>
      <span id="brandSubtitle">World Cup Prediction Center</span>
    </div>
    <div class="top-actions">
      <button id="languageToggle" class="lang-button" type="button"><i data-lucide="languages"></i> 中文</button>
      <button id="refreshButton" class="icon-button" type="button" title="Refresh"><i data-lucide="refresh-cw"></i> <span id="refreshLabel">Refresh</span></button>
    </div>
  </header>

  <main>
    <div class="app-shell" id="app">
      <section class="status-row" id="globalStatus">
        <span class="pill">Loading fixtures</span>
      </section>

      <section class="workspace">
        <aside class="fixture-rail" aria-label="Fixtures">
          <div class="section-heading">
            <div>
              <h2 id="fixtureRailTitle">Fixtures</h2>
              <span id="fixtureCount">0</span>
            </div>
            <span class="pill good" id="fixtureSourcePill">Live API</span>
          </div>
          <div class="fixture-list" id="fixtureList"></div>
        </aside>

        <section class="match-deck" aria-label="Match prediction">
          <div class="match-visual">
            <div class="status-row" id="matchMeta"></div>
            <div class="scoreboard">
              <article class="team home" id="homeTeam"></article>
              <article class="score-center">
                <div class="score-label" id="scoreLabel">Predicted score</div>
                <div class="score" id="predictedScore"><span>-</span><em>:</em><span>-</span></div>
                <div class="verdict">
                  <strong id="verdictTitle">Waiting for fixtures</strong>
                  <span id="verdictSummary">The page reads the verified fixture feed and calls the model automatically.</span>
                </div>
              </article>
              <article class="team away" id="awayTeam"></article>
            </div>
            <div class="probability-strip" id="probabilityStrip"></div>
          </div>

          <div class="content-grid">
            <div class="main-stack">
              <section class="panel">
                <div class="section-heading">
                  <div>
                    <h2 id="overviewTitle">Prediction Summary</h2>
                    <p class="section-lead" id="overviewLead">Core probability, score path, and match context are shown without manual parameter entry.</p>
                  </div>
                </div>
                <div class="signal-grid" id="signalGrid"></div>
                <div class="compact-list" id="scorelines"></div>
              </section>

              <section class="panel">
                <div class="section-heading">
                  <div>
                    <h2 id="factorTitle">Model Factors</h2>
                    <p class="section-lead" id="factorLead">Core factors stay visible; lower-confidence detail factors are expandable.</p>
                  </div>
                </div>
                <div class="factor-list" id="factorList"></div>
              </section>

              <section class="panel">
                <div class="section-heading">
                  <div>
                    <h2 id="playerTitle">Key Players</h2>
                    <p class="section-lead" id="playerLead">Official lineups will replace the placeholder layer when available.</p>
                  </div>
                </div>
                <div class="players" id="players"></div>
              </section>
            </div>

            <aside class="side-stack">
              <section class="panel risk-panel">
                <div class="risk-top">
                  <h2 id="riskTitle">Upset Risk</h2>
                  <span class="risk-level" id="riskLevel">--</span>
                </div>
                <p class="section-lead" id="riskText">Waiting for model output.</p>
                <div class="tag-cloud" id="riskTags"></div>
              </section>

              <section class="panel">
                <div class="section-heading">
                  <div>
                    <h2 id="motivationTitle">Qualification Motivation</h2>
                    <p class="section-lead" id="motivationLead">Group-path pressure and rotation risk are calculated automatically.</p>
                  </div>
                </div>
                <div class="compact-list" id="motivationList"></div>
              </section>

              <section class="panel">
                <div class="section-heading">
                  <div>
                    <h2 id="marketTitle">Market And Data</h2>
                    <p class="section-lead" id="marketLead">Odds, source state, and model freshness are shown directly on the delivery page.</p>
                  </div>
                </div>
                <div class="compact-list" id="marketList"></div>
                <div class="source-row" id="sourceBadges"></div>
              </section>

              <section class="panel">
                <div class="section-heading">
                  <div>
                    <h2 id="sourceTitle">Source Status</h2>
                    <p class="section-lead" id="sourceText">Loading source status.</p>
                  </div>
                </div>
                <p class="fine-print" id="disclaimer">MatchOracle outputs probabilities and risk explanations, not betting advice.</p>
              </section>
            </aside>
          </div>
        </section>
      </section>
    </div>
  </main>

  <script src="https://unpkg.com/lucide@0.468.0/dist/umd/lucide.min.js"></script>
  <script>
    const savedLanguage = (() => {
      try { return window.localStorage?.getItem("matchoracle.lang"); } catch (error) { return null; }
    })();

    const state = {
      fixtures: [],
      activeId: null,
      activeFixture: null,
      prediction: null,
      readiness: null,
      feedStatus: null,
      lang: savedLanguage === "en" ? "en" : "zh",
      lastUpdatedAt: null,
      loading: false,
    };

    const AUTO_REFRESH_MS = 90 * 1000;

    const copy = {
      zh: {
        brandSubtitle: "世界杯预测中心",
        refresh: "刷新",
        fixtureRailTitle: "全部已接入赛事",
        fixtureUnit: "场赛事",
        liveApi: "真实数据",
        loading: "正在加载赛事",
        sourceReady: "真实赛程已同步",
        sampleBlocked: "真实赛程未同步",
        scoreLabel: "预测比分",
        finalScore: "完赛比分",
        predictionPending: "预测待计算",
        matchupPending: "对阵待定",
        overviewTitle: "胜平负与比分概率",
        overviewLead: "胜平负使用同一组 canonical 概率；比分列表展示单个比分概率，不等同于三项胜率。",
        factorTitle: "模型因素",
        factorLead: "必须展示因子保持可见，条件因子放入展开查看；低价值或敏感因子隐藏。",
        playerTitle: "关键球员",
        playerLead: "官方首发未接入时不伪装；可用球员层会在这里展示。",
        riskTitle: "爆冷风险",
        motivationTitle: "出线动机",
        motivationLead: "根据当前积分、剩余赛程和48队第三名规则自动计算。",
        marketTitle: "市场与数据",
        marketLead: "市场隐含概率单独展示，只用于校准和分歧提示，不覆盖 canonical 胜平负口径。",
        sourceTitle: "数据源状态",
        disclaimer: "MatchOracle 输出的是概率与风险解释，不是下注建议；官方首发、伤停、赔率变化和赛制动机会改变最终置信度。",
        homeWin: "主胜",
        draw: "平局",
        awayWin: "客胜",
        confidence: "置信度",
        highestProbability: "最高概率",
        expectedGoals: "预期进球",
        marketHint: "市场提示",
        marketConnected: "赔率已接入",
        valueSide: "价值方向",
        dataReliability: "数据可靠性",
        matchContext: "比赛语境",
        scorePath: "单比分概率",
        noPrediction: "该场对阵尚未确定，只展示赛程时间和轮次。",
        noLineup: "官方首发未接入",
        marketUnavailable: "赔率未接入",
        sourceMode: "源模式",
        snapshot: "快照",
        beijingTime: "北京时间",
        etTime: "美国东部时间",
        requiredFactors: "必须展示",
        advancedFactors: "展开查看",
        dataStatus: "数据状态",
        high: "高",
        medium: "中",
        low: "低",
        neutral: "中性",
        homeEdge: "偏主队",
        awayEdge: "偏客队",
        win: "胜",
        loss: "负",
        details: "详情",
        selected: "已选择",
        autoRefresh: "自动刷新",
        updated: "更新",
        motivationScore: "战意分",
        rotationRisk: "轮换风险",
        mustWin: "必须赢",
        needDraw: "平局可接受",
        alreadyQualified: "出线压力低",
        eliminatedRisk: "出线困难",
        openStatus: "形势开放",
        qualificationOutcomes: "出线率",
      },
      en: {
        brandSubtitle: "World Cup Prediction Center",
        refresh: "Refresh",
        fixtureRailTitle: "All Connected Fixtures",
        fixtureUnit: "fixtures",
        liveApi: "Live Data",
        loading: "Loading fixtures",
        sourceReady: "Verified fixtures synced",
        sampleBlocked: "Verified fixtures not synced",
        scoreLabel: "Predicted Score",
        finalScore: "Final Score",
        predictionPending: "Prediction pending",
        matchupPending: "Matchup pending",
        overviewTitle: "1X2 And Score Probabilities",
        overviewLead: "1X2 uses one canonical probability set; score rows show individual scoreline probabilities, not outcome totals.",
        factorTitle: "Model Factors",
        factorLead: "Core decision factors stay visible; conditional detail factors are expandable.",
        playerTitle: "Key Players",
        playerLead: "Official lineups are not faked; available player layers appear here.",
        riskTitle: "Upset Risk",
        motivationTitle: "Qualification Motivation",
        motivationLead: "Calculated from standings, remaining schedule, and the 48-team third-place rule.",
        marketTitle: "Market And Data",
        marketLead: "Market-implied probability is shown separately for calibration and disagreement, not as the canonical 1X2 line.",
        sourceTitle: "Source Status",
        disclaimer: "MatchOracle outputs probabilities and risk explanations, not betting advice. Lineups, injuries, odds movement, and tournament context can change confidence.",
        homeWin: "Home win",
        draw: "Draw",
        awayWin: "Away win",
        confidence: "confidence",
        highestProbability: "Highest probability",
        expectedGoals: "Expected goals",
        marketHint: "Market hint",
        marketConnected: "Odds connected",
        valueSide: "Value side",
        dataReliability: "Data reliability",
        matchContext: "Match context",
        scorePath: "Scoreline probability",
        noPrediction: "This matchup is not determined yet; only schedule time and round are shown.",
        noLineup: "Official lineups unavailable",
        marketUnavailable: "Odds unavailable",
        sourceMode: "Source mode",
        snapshot: "Snapshot",
        beijingTime: "Beijing Time",
        etTime: "US Eastern Time",
        requiredFactors: "Core factors",
        advancedFactors: "Expand details",
        dataStatus: "Data status",
        high: "High",
        medium: "Medium",
        low: "Low",
        neutral: "Neutral",
        homeEdge: "Home edge",
        awayEdge: "Away edge",
        win: "Win",
        loss: "Loss",
        details: "Details",
        selected: "Selected",
        autoRefresh: "Auto refresh",
        updated: "Updated",
        motivationScore: "Motivation",
        rotationRisk: "Rotation risk",
        mustWin: "Must win",
        needDraw: "Draw enough",
        alreadyQualified: "Low pressure",
        eliminatedRisk: "Long shot",
        openStatus: "Open path",
        qualificationOutcomes: "Advance odds",
      },
    };

    const REQUIRED_FACTOR_IDS = ["F01", "F05", "F07", "F12", "F13"];
    const ADVANCED_FACTOR_IDS = ["F02", "F04", "F08", "F11", "F16"];
    const HIDDEN_FACTOR_IDS = new Set(["F03", "F06", "F10", "F14", "F17"]);
    const FACTOR_LABELS = {
      zh: {
        F01: "球队真实强度",
        F02: "近期状态与比赛节奏",
        F04: "球员与预计首发强度",
        F05: "赛制动机与轮换概率",
        F07: "近攻质量与 xG",
        F08: "防守与门将稳定性",
        F11: "环境与行动记忆",
        F12: "市场概率与赔率分线",
        F13: "布局对位与布局配置性",
        F16: "定位球事件风险",
      },
      en: {
        F01: "True Team Strength",
        F02: "Recent Form And Tempo",
        F04: "Player And Expected XI Strength",
        F05: "Tournament Motivation And Rotation",
        F07: "Attacking Quality And xG",
        F08: "Defensive And Keeper Stability",
        F11: "Environment And Travel Memory",
        F12: "Market Probability And Odds Lines",
        F13: "Shape Matchup And Tactical Fit",
        F16: "Set-Piece Event Risk",
      },
    };
    const FACTOR_REASONS = {
      zh: {
        F01: "球队真实强度是判断实力差距的核心节点。",
        F05: "赛制动机和轮换概率是世界杯小组赛的高价值差异化因子。",
        F07: "近攻质量与 xG 是现代足球分析的标配。",
        F12: "市场概率与赔率分线体现市场集体智慧，闭合差是核心信号。",
        F13: "阵型对位与配置性展示具体位置关系，适合深度用户判断。",
        F02: "近期状态有参考价值，需要结合真实强度一起看。",
        F04: "球员与预计首发强度依赖临场数据，未到官方首发前只作为辅助。",
        F08: "防守与门将稳定性对低比分场次更有价值。",
        F11: "环境、旅程和适应成本权重较低，但可辅助解释。",
        F16: "定位球事件风险适合查看细节，不作为主结论。",
      },
      en: {
        F01: "True team strength is the core gap signal.",
        F05: "Tournament motivation and rotation risk are high-value World Cup context.",
        F07: "Recent attacking quality and xG are standard modern football signals.",
        F12: "Market probability and line splits expose market-implied wisdom.",
        F13: "Shape matchup and tactical fit show the positional edge.",
        F02: "Recent form is useful only when read beside true strength.",
        F04: "Player and expected XI strength depends on late lineup quality.",
        F08: "Defensive and keeper stability matters most in low-score matches.",
        F11: "Travel and environment context is lower weight but useful.",
        F16: "Set-piece event risk is a detail layer, not the headline verdict.",
      },
    };

    const resultLabels = {
      HOME_WIN: {zh: "主胜", en: "Home win"},
      DRAW: {zh: "平局", en: "Draw"},
      AWAY_WIN: {zh: "客胜", en: "Away win"},
      ABORTED: {zh: "暂停输出", en: "Paused"},
    };

    const $ = (id) => document.getElementById(id);
    const t = (key) => copy[state.lang]?.[key] || key;

    function escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    function hasCjk(value) {
      return /[\u3400-\u9fff]/.test(String(value || ""));
    }

    function localized(zhValue, enValue) {
      return state.lang === "zh" ? (zhValue || enValue || "") : (enValue || zhValue || "");
    }

    function teamName(team) {
      return state.lang === "zh" ? (team?.nameZh || team?.name || "--") : (team?.name || team?.nameZh || "--");
    }

    function playerName(player) {
      return state.lang === "zh" ? (player?.nameZh || player?.name || "--") : (player?.name || player?.nameZh || "--");
    }

    function playerNote(player) {
      const note = player?.note || "";
      if (state.lang === "en" && hasCjk(note)) return player?.tier || "";
      return note;
    }

    function percent(value) {
      const number = Number(value || 0);
      if (!Number.isFinite(number)) return "--";
      const normalized = number > 1 && number <= 100 ? number / 100 : number;
      return `${Math.round(normalized * 1000) / 10}%`;
    }

    function probabilityWidth(value) {
      const number = Number(value || 0);
      if (!Number.isFinite(number)) return 1;
      const normalized = number > 1 && number <= 100 ? number / 100 : number;
      return Math.max(1, Math.min(100, normalized * 100));
    }

    function numberText(value, digits = 2) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(digits) : "--";
    }

    function probabilitySource(prediction) {
      return prediction?.canonicalProbability?.probabilities || prediction?.probabilities || {};
    }

    function kickoffIso(fixture) {
      return fixture?.kickoffAt || fixture?.predictionPayload?.match?.datetime || "";
    }

    function fixtureTimeValue(fixture) {
      const timestamp = Date.parse(kickoffIso(fixture));
      return Number.isFinite(timestamp) ? timestamp : Number.MAX_SAFE_INTEGER;
    }

    function formatKickoff(fixture) {
      const date = new Date(kickoffIso(fixture));
      if (!Number.isFinite(date.getTime())) return fixture?.kickoffLabel || "--";
      const timeZone = state.lang === "zh" ? "Asia/Shanghai" : "America/New_York";
      const locale = state.lang === "zh" ? "zh-CN" : "en-US";
      const label = state.lang === "zh" ? "北京时间" : "ET";
      return new Intl.DateTimeFormat(locale, {
        timeZone,
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: state.lang === "en",
      }).format(date) + ` ${label}`;
    }

    function formatTimestamp(value) {
      const date = new Date(value);
      if (!Number.isFinite(date.getTime())) return "--";
      const timeZone = state.lang === "zh" ? "Asia/Shanghai" : "America/New_York";
      const locale = state.lang === "zh" ? "zh-CN" : "en-US";
      return new Intl.DateTimeFormat(locale, {
        timeZone,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: state.lang === "en",
      }).format(date);
    }

    function scoreLine(fixture) {
      const score = fixture?.score;
      if (!score || score.home === undefined || score.away === undefined) return "";
      return `${score.home}-${score.away}`;
    }

    function fixtureDisplayName(fixture) {
      if (fixture?.displayTitle || fixture?.displayTitleEn) return localized(fixture.displayTitle, fixture.displayTitleEn);
      return `${teamName(fixture?.home)} vs ${teamName(fixture?.away)}`;
    }

    function fixtureStage(fixture) {
      return localized(fixture?.stageLabel, fixture?.stageLabelEn);
    }

    function fixtureVenue(fixture) {
      const venue = localized(fixture?.venueLabel, fixture?.venueLabelEn);
      if (state.lang === "en" && venue === "场馆待定") return "Venue pending";
      return venue || "--";
    }

    function fixtureStatus(fixture) {
      return localized(fixture?.statusLabel, fixture?.statusLabelEn);
    }

    function formDots(form) {
      const outcomes = String(form || "").toUpperCase().match(/[WDL]/g) || [];
      if (!outcomes.length) return "";
      const classByOutcome = {W: "win", D: "draw", L: "loss"};
      const labelByOutcome = {W: t("win"), D: t("draw"), L: t("loss")};
      return `<span class="form-dots" aria-label="${escapeHtml(form)}">` + outcomes.map((outcome) =>
        `<i class="form-dot ${classByOutcome[outcome]}" title="${escapeHtml(labelByOutcome[outcome])}"></i>`
      ).join("") + `</span>`;
    }

    function teamBlock(team, side) {
      return `
        <div class="flag-mark" aria-label="${escapeHtml(teamName(team))} flag">${escapeHtml(team?.flag || "◇")}</div>
        <div class="team-name">
          ${side === "home" ? `<h1>${escapeHtml(teamName(team))}</h1>` : `<h2>${escapeHtml(teamName(team))}</h2>`}
          <span>${escapeHtml(team?.shortName || "--")} ${formDots(team?.form)}</span>
        </div>
      `;
    }

    function factorCode(factor) {
      const match = String(factor?.id || "").match(/^F\d{2}/);
      return match ? match[0] : "";
    }

    function dataQualityText(value) {
      const quality = String(value || "").toUpperCase();
      const map = state.lang === "zh"
        ? {HIGH: t("high"), MEDIUM: t("medium"), LOW: t("low")}
        : {HIGH: t("high"), MEDIUM: t("medium"), LOW: t("low")};
      return map[quality] || value || "--";
    }

    function confidenceText(value) {
      return dataQualityText(value);
    }

    function riskLevelText(value) {
      return dataQualityText(value);
    }

    function impactText(value) {
      const impact = String(value || "").toUpperCase();
      if (impact === "POSITIVE_HOME") return t("homeEdge");
      if (impact === "POSITIVE_AWAY") return t("awayEdge");
      return t("neutral");
    }

    function impactClass(value) {
      if (value === "POSITIVE_HOME") return "home";
      if (value === "POSITIVE_AWAY") return "away";
      return "neutral";
    }

    function outcomeName(value) {
      const key = String(value || "").toLowerCase();
      if (key === "home") return t("homeWin");
      if (key === "away") return t("awayWin");
      if (key === "draw") return t("draw");
      return value || "--";
    }

    function localizedModelText(value) {
      if (state.lang !== "zh") return value || "";
      return String(value || "")
        .replace(/\bHIGH\b/g, t("high"))
        .replace(/\bMEDIUM\b/g, t("medium"))
        .replace(/\bLOW\b/g, t("low"));
    }

    function hasCanonicalProbabilities(probs) {
      return ["home", "draw", "away"].every((key) => Number.isFinite(Number(probs?.[key])));
    }

    function predictionSummaryText(fixture, prediction, resultLabel, probs) {
      const score = prediction?.scorePrediction?.predicted || {};
      if (hasCanonicalProbabilities(probs) && score.home !== undefined && score.away !== undefined) {
        const version = prediction?.modelVersion || "V4-P0";
        const confidence = confidenceText(prediction?.verdict?.confidence);
        if (state.lang === "zh") {
          return `${fixtureDisplayName(fixture)} 的${version}基线预测为 ${score.home}-${score.away}。当前胜平负概率为主胜${percent(probs.home)}、平局${percent(probs.draw)}、客胜${percent(probs.away)}，置信度为${confidence}。`;
        }
        return `${fixtureDisplayName(fixture)} ${version} baseline score is ${score.home}-${score.away}. Current 1X2 probabilities are home ${percent(probs.home)}, draw ${percent(probs.draw)}, away ${percent(probs.away)} with ${confidence.toLowerCase()} confidence.`;
      }
      const summary = prediction?.verdict?.executiveSummary || "";
      if (state.lang === "zh" || (summary && !hasCjk(summary))) {
        return localizedModelText(summary) || localized(fixture.broadcastNote, fixture.broadcastNoteEn) || "";
      }
      return `Model leans ${resultLabel.toLowerCase()} with ${confidenceText(prediction?.verdict?.confidence)} confidence. ${teamName(fixture.home)} ${percent(probs.home)}, draw ${percent(probs.draw)}, ${teamName(fixture.away)} ${percent(probs.away)}.`;
    }

    function riskSummaryText(risk) {
      const explanation = risk?.explanation || "";
      if (state.lang === "zh" || (explanation && !hasCjk(explanation))) return localizedModelText(explanation) || "--";
      const triggers = (risk?.triggers || []).slice(0, 3).map((trigger) => trigger.code).join(", ");
      return `Risk level ${riskLevelText(risk?.upsetRiskLevel)}. Main signals: ${triggers || "baseline model volatility"}.`;
    }

    function statusText(status) {
      const value = String(status || "").toUpperCase();
      if (value === "MUST_WIN") return t("mustWin");
      if (value === "NEED_DRAW") return t("needDraw");
      if (value === "ALREADY_QUALIFIED") return t("alreadyQualified");
      if (value === "ELIMINATED_RISK") return t("eliminatedRisk");
      if (value === "OPEN") return t("openStatus");
      return t("neutral");
    }

    function outcomeText(scores) {
      const source = scores || {};
      const labels = state.lang === "zh" ? {W: "胜", D: "平", L: "负"} : {W: "W", D: "D", L: "L"};
      return `${labels.W} ${percent(source.W || 0)} · ${labels.D} ${percent(source.D || 0)} · ${labels.L} ${percent(source.L || 0)}`;
    }

    function hasOutcomeScores(scores) {
      return Object.values(scores || {}).some((value) => Number(value || 0) > 0);
    }

    function motivationReason(context) {
      const reason = context?.reasoning || "";
      if (state.lang === "zh" || !hasCjk(reason)) return reason || t("neutral");
      return "Early group-stage baseline; path pressure is not active yet.";
    }

    function renderMotivation(fixture) {
      const context = fixture?.qualificationContext || fixture?.predictionPayload?.matchContext || {};
      if (!context || !Object.keys(context).length) {
        $("motivationList").innerHTML = `<div class="compact-row"><span class="outcome-dot"></span><strong>${escapeHtml(t("motivationTitle"))}</strong><span>--</span></div>`;
        return;
      }
      const rows = [
        [`${teamName(fixture.home)} · ${statusText(context.homeQualificationStatus)}`, `${t("motivationScore")} ${numberText(context.homeMotivationScore, 1)} / ${t("rotationRisk")} ${percent(context.homeRotationRisk || 0)}`],
        [`${teamName(fixture.away)} · ${statusText(context.awayQualificationStatus)}`, `${t("motivationScore")} ${numberText(context.awayMotivationScore, 1)} / ${t("rotationRisk")} ${percent(context.awayRotationRisk || 0)}`],
      ];
      if (hasOutcomeScores(context.homeQualificationByOutcome) || hasOutcomeScores(context.awayQualificationByOutcome)) {
        rows.push(
          [t("qualificationOutcomes"), `${teamName(fixture.home)} ${outcomeText(context.homeQualificationByOutcome)}`],
          [t("qualificationOutcomes"), `${teamName(fixture.away)} ${outcomeText(context.awayQualificationByOutcome)}`],
        );
      } else {
        rows.push([t("matchContext"), motivationReason(context)]);
      }
      $("motivationList").innerHTML = rows.map(([label, value]) => `
        <div class="compact-row">
          <span class="outcome-dot"></span>
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(value)}</span>
        </div>
      `).join("");
    }

    function attachIcons() {
      window.lucide?.createIcons();
    }

    function renderShellCopy() {
      document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
      document.title = state.lang === "zh" ? "MatchOracle 世界杯预测中心" : "MatchOracle World Cup Prediction Center";
      $("brandSubtitle").textContent = t("brandSubtitle");
      $("refreshLabel").textContent = t("refresh");
      $("languageToggle").innerHTML = `<i data-lucide="languages"></i> ${state.lang === "zh" ? "EN" : "中文"}`;
      $("fixtureRailTitle").textContent = t("fixtureRailTitle");
      $("fixtureSourcePill").textContent = t("liveApi");
      $("scoreLabel").textContent = t("scoreLabel");
      $("overviewTitle").textContent = t("overviewTitle");
      $("overviewLead").textContent = t("overviewLead");
      $("factorTitle").textContent = t("factorTitle");
      $("factorLead").textContent = t("factorLead");
      $("playerTitle").textContent = t("playerTitle");
      $("playerLead").textContent = t("playerLead");
      $("riskTitle").textContent = t("riskTitle");
      $("motivationTitle").textContent = t("motivationTitle");
      $("motivationLead").textContent = t("motivationLead");
      $("marketTitle").textContent = t("marketTitle");
      $("marketLead").textContent = t("marketLead");
      $("sourceTitle").textContent = t("sourceTitle");
      $("disclaimer").textContent = t("disclaimer");
    }

    function renderGlobalStatus() {
      const feed = state.feedStatus || {};
      const source = feed.fallback ? t("sampleBlocked") : t("sourceReady");
      $("globalStatus").innerHTML = `
        <span class="pill ${feed.fallback ? "hot" : "good"}">${escapeHtml(source)}</span>
        <span class="pill">${escapeHtml(state.fixtures.length)} ${escapeHtml(t("fixtureUnit"))}</span>
        <span class="pill">${escapeHtml(state.lang === "zh" ? t("beijingTime") : t("etTime"))}</span>
        <span class="pill">${escapeHtml(t("autoRefresh"))} 90s</span>
        <span class="pill">${escapeHtml(t("updated"))} ${escapeHtml(formatTimestamp(state.lastUpdatedAt))}</span>
        <span class="pill">V4-P0</span>
      `;
      $("sourceText").textContent = localized(feed.message, feed.messageEn) || source;
    }

    function renderFixtures() {
      $("fixtureCount").textContent = `${state.fixtures.length} ${t("fixtureUnit")}`;
      if (!state.fixtures.length) {
        $("fixtureList").innerHTML = `<div class="empty-state"><strong>${escapeHtml(t("sampleBlocked"))}</strong><span>${escapeHtml(localized(state.feedStatus?.message, state.feedStatus?.messageEn) || "")}</span></div>`;
        return;
      }
      $("fixtureList").innerHTML = state.fixtures.map((fixture) => `
        <button type="button" class="fixture-card ${fixture.id === state.activeId ? "active" : ""}" data-match-id="${escapeHtml(fixture.id)}">
          <div class="fixture-card-top">
            <span>${escapeHtml(fixtureStatus(fixture))}</span>
            <span>${escapeHtml(fixtureStage(fixture))}</span>
          </div>
          <div class="fixture-card-mid">
            <strong>${escapeHtml(fixtureDisplayName(fixture))}</strong>
            <span>${escapeHtml(scoreLine(fixture) || (fixture.id === state.activeId ? t("selected") : t("details")))}</span>
          </div>
          <div class="fixture-card-foot">
            <span>${escapeHtml(formatKickoff(fixture))}</span>
            <span>${escapeHtml(fixtureVenue(fixture))}</span>
          </div>
        </button>
      `).join("");
      document.querySelectorAll("[data-match-id]").forEach((button) => {
        button.addEventListener("click", () => selectFixture(button.dataset.matchId));
      });
    }

    function renderMatchShell(fixture) {
      $("matchMeta").innerHTML = `
        <span class="pill hot">${escapeHtml(fixtureStatus(fixture))}</span>
        <span class="pill">${escapeHtml(fixtureStage(fixture))}</span>
        <span class="pill">${escapeHtml(formatKickoff(fixture))}</span>
        <span class="pill">${escapeHtml(fixtureVenue(fixture))}</span>
      `;
      $("homeTeam").innerHTML = teamBlock(fixture.home, "home");
      $("awayTeam").innerHTML = teamBlock(fixture.away, "away");
      const finalScore = scoreLine(fixture);
      $("scoreLabel").textContent = finalScore ? t("finalScore") : t("scoreLabel");
      $("predictedScore").innerHTML = finalScore
        ? `<span>${escapeHtml(fixture.score.home)}</span><em>:</em><span>${escapeHtml(fixture.score.away)}</span>`
        : `<span>-</span><em>:</em><span>-</span>`;
      $("verdictTitle").textContent = fixtureDisplayName(fixture);
      $("verdictSummary").textContent = localized(fixture.broadcastNote, fixture.broadcastNoteEn) || fixtureStatus(fixture);
      $("probabilityStrip").innerHTML = ["home", "draw", "away"].map((key) => `
        <div class="probability-lane">
          <div class="prob-head"><span>${escapeHtml(key === "home" ? t("homeWin") : key === "away" ? t("awayWin") : t("draw"))}</span><strong>--</strong></div>
          <div class="bar"><i style="width:1%"></i></div>
        </div>
      `).join("");
      renderSignals(fixture, null);
      renderPlayers(fixture);
      renderMotivation(fixture);
      renderSources(fixture);
      if (!fixture.predictionAvailable) {
        renderPendingPanels();
      }
    }

    function renderPendingPanels() {
      $("signalGrid").innerHTML = [
        [t("matchupPending"), "--", t("noPrediction")],
        [t("sourceMode"), state.feedStatus?.sourceMode || "--", t("sourceReady")],
        [t("snapshot"), state.feedStatus?.latestSnapshotTime || "--", t("liveApi")],
      ].map(([label, value, note]) => `<div class="signal"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note)}</span></div>`).join("");
      $("scorelines").innerHTML = `<div class="compact-row"><span class="outcome-dot"></span><strong>${escapeHtml(t("scorePath"))}</strong><span>${escapeHtml(t("noPrediction"))}</span></div>`;
      $("factorList").innerHTML = `<div class="factor-row"><div class="factor-title"><strong>${escapeHtml(t("matchupPending"))}</strong><span>${escapeHtml(t("noPrediction"))}</span></div><span class="impact neutral">--</span></div>`;
      $("riskLevel").textContent = "--";
      $("riskText").textContent = t("noPrediction");
      $("riskTags").innerHTML = `<span class="tag">${escapeHtml(t("matchupPending"))}</span>`;
      $("motivationList").innerHTML = `<div class="compact-row"><span class="outcome-dot"></span><strong>${escapeHtml(t("motivationTitle"))}</strong><span>${escapeHtml(t("noPrediction"))}</span></div>`;
      $("marketList").innerHTML = `<div class="compact-row"><span class="outcome-dot"></span><strong>${escapeHtml(t("marketUnavailable"))}</strong><span>--</span></div>`;
    }

    function renderPrediction(fixture, prediction) {
      const probs = probabilitySource(prediction);
      const score = prediction?.scorePrediction?.predicted || {};
      if (!scoreLine(fixture)) {
        $("scoreLabel").textContent = t("scoreLabel");
        $("predictedScore").innerHTML = `<span>${escapeHtml(score.home ?? "-")}</span><em>:</em><span>${escapeHtml(score.away ?? "-")}</span>`;
      }
      const result = prediction?.verdict?.result;
      const resultLabel = localized(resultLabels[result]?.zh, resultLabels[result]?.en) || t("predictionPending");
      const confidence = confidenceText(prediction?.verdict?.confidence);
      $("verdictTitle").textContent = `${resultLabel} · ${confidence} ${t("confidence")}`;
      $("verdictSummary").textContent = predictionSummaryText(fixture, prediction, resultLabel, probs);
      const lanes = [
        ["home", t("homeWin"), teamName(fixture.home)],
        ["draw", t("draw"), t("draw")],
        ["away", t("awayWin"), teamName(fixture.away)],
      ];
      $("probabilityStrip").innerHTML = lanes.map(([key, label, team]) => `
        <div class="probability-lane">
          <div class="prob-head">
            <span>${escapeHtml(label)} · ${escapeHtml(team)}</span>
            <strong>${percent(probs[key])}</strong>
          </div>
          <div class="bar"><i style="width:${probabilityWidth(probs[key])}%"></i></div>
        </div>
      `).join("");
      renderSignals(fixture, prediction);
      renderScorelines(prediction);
      renderFactors(prediction);
      renderMarket(prediction);
      renderRisk(prediction);
    }

    function renderSignals(fixture, prediction) {
      const probs = probabilitySource(prediction);
      const maxProbability = Math.max(Number(probs.home || 0), Number(probs.draw || 0), Number(probs.away || 0));
      const scorePrediction = prediction?.scorePrediction || {};
      const reliability = prediction?.dataReliability || {};
      const market = prediction?.marketAnalysis || {};
      const best = market.bestValue || {};
      const signals = [
        [t("highestProbability"), maxProbability ? percent(maxProbability) : "--", "90 min"],
        [t("expectedGoals"), prediction ? `${numberText(scorePrediction.homeLambda)} : ${numberText(scorePrediction.awayLambda)}` : "--", "lambda"],
        [t("marketHint"), market.probabilities ? (best.outcome ? `${t("valueSide")} ${outcomeName(best.outcome)}` : t("marketConnected")) : t("marketUnavailable"), "market"],
        [t("dataReliability"), prediction ? `${reliability.status || "--"} · ${reliability.score ?? "--"}` : "--", "source check"],
        [state.lang === "zh" ? t("beijingTime") : t("etTime"), formatKickoff(fixture), fixtureVenue(fixture)],
        [t("matchContext"), fixtureStage(fixture), localized(fixture.broadcastNote, fixture.broadcastNoteEn)],
      ];
      $("signalGrid").innerHTML = signals.map(([label, value, note]) => `
        <div class="signal">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
          <span>${escapeHtml(note)}</span>
        </div>
      `).join("");
    }

    function renderScorelines(prediction) {
      const rows = (prediction?.scorePrediction?.topScenarios || []).slice(0, 6);
      $("scorelines").innerHTML = rows.length ? rows.map((item) => `
        <div class="compact-row">
          <span class="outcome-dot"></span>
          <strong>${escapeHtml(item.score)}</strong>
          <span>${percent(item.probability)}</span>
        </div>
      `).join("") : `<div class="compact-row"><span class="outcome-dot"></span><strong>${escapeHtml(t("scorePath"))}</strong><span>--</span></div>`;
    }

    function renderFactorRow(factor, code, tone) {
      const present = Boolean(factor);
      return `
        <article class="factor-row ${tone}">
          <div class="factor-title">
            <strong>${escapeHtml(code)} · ${escapeHtml(FACTOR_LABELS[state.lang]?.[code] || factor?.name || code)}</strong>
            <span>${escapeHtml(FACTOR_REASONS[state.lang]?.[code] || "")}</span>
            <div class="factor-meta">
              <span>${escapeHtml(t("dataStatus"))} ${escapeHtml(present ? dataQualityText(factor.dataQuality) : "--")}</span>
              <span>${escapeHtml(present ? impactText(factor.impact) : "--")}</span>
              <span>${escapeHtml(present ? numberText(factor.impactScore, 2) : "--")}</span>
            </div>
          </div>
          <span class="impact ${impactClass(factor?.impact)}">${escapeHtml(present ? numberText(factor.impactScore, 1) : "--")}</span>
        </article>
      `;
    }

    function renderFactors(prediction) {
      const factors = (prediction?.factors || []).filter((factor) => !HIDDEN_FACTOR_IDS.has(factorCode(factor)));
      const byCode = new Map(factors.map((factor) => [factorCode(factor), factor]));
      const coreRows = REQUIRED_FACTOR_IDS.map((code) => renderFactorRow(byCode.get(code), code, "core")).join("");
      const advancedRows = ADVANCED_FACTOR_IDS.map((code) => renderFactorRow(byCode.get(code), code, "optional")).join("");
      $("factorList").innerHTML = `
        <div class="factor-group">
          <div class="factor-group-title">${escapeHtml(t("requiredFactors"))}</div>
          ${coreRows}
        </div>
        <details class="factor-group">
          <summary><span>${escapeHtml(t("advancedFactors"))}</span><span>${ADVANCED_FACTOR_IDS.length}</span></summary>
          ${advancedRows}
        </details>
      `;
    }

    function renderPlayers(fixture) {
      const lineups = fixture?.lineups || {};
      const side = (title, formation, players) => `
        <article class="player-side">
          <header><strong>${escapeHtml(title)}</strong><span>${escapeHtml(formation || "--")}</span></header>
          <div class="player-list">
            ${(players || []).map((player) => `
              <div class="player">
                <div class="player-name">
                  <strong>${escapeHtml(playerName(player))}</strong>
                  <span>${escapeHtml(player.tier || "--")} · ${escapeHtml(playerNote(player))}</span>
                </div>
                <span class="role">${escapeHtml(player.role || "--")}</span>
              </div>
            `).join("") || `<div class="player"><div class="player-name"><strong>${escapeHtml(t("noLineup"))}</strong><span>--</span></div><span class="role">--</span></div>`}
          </div>
        </article>
      `;
      $("players").innerHTML = [
        side(`${fixture?.home?.flag || ""} ${teamName(fixture?.home)}`, lineups.homeFormation, lineups.homePlayers),
        side(`${fixture?.away?.flag || ""} ${teamName(fixture?.away)}`, lineups.awayFormation, lineups.awayPlayers),
      ].join("");
    }

    function renderMarket(prediction) {
      const market = prediction?.marketAnalysis || {};
      const movement = market.lineMovement?.strongestMove;
      const rows = [
        [t("marketTitle"), market.probabilities ? `${t("homeWin")} ${percent(market.probabilities.home)} / ${t("draw")} ${percent(market.probabilities.draw)} / ${t("awayWin")} ${percent(market.probabilities.away)}` : t("marketUnavailable")],
        [t("valueSide"), outcomeName(market.bestValue?.outcome)],
        [t("snapshot"), movement ? `${movement.outcome} ${numberText(movement.probabilityDelta * 100, 1)} pts` : "--"],
      ];
      $("marketList").innerHTML = rows.map(([label, value]) => `
        <div class="compact-row">
          <span class="outcome-dot"></span>
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(value)}</span>
        </div>
      `).join("");
    }

    function renderRisk(prediction) {
      const risk = prediction?.upsetRisk || {};
      $("riskLevel").textContent = riskLevelText(risk.upsetRiskLevel);
      $("riskText").textContent = riskSummaryText(risk);
      const triggers = (risk.triggers || []).slice(0, 6);
      $("riskTags").innerHTML = triggers.length ? triggers.map((trigger) => `
        <span class="tag" title="${escapeHtml(trigger.message)}">${escapeHtml(trigger.code)}</span>
      `).join("") : `<span class="tag">NO_MAJOR_TRIGGER</span>`;
    }

    function renderSources(fixture) {
      const feed = state.feedStatus || {};
      const badges = fixture?.sourceBadges || [];
      const badgesEn = fixture?.sourceBadgesEn || [];
      $("sourceBadges").innerHTML = (state.lang === "zh" ? badges : badgesEn).map((badge) => `<span class="pill">${escapeHtml(badge)}</span>`).join("");
      $("sourceText").textContent = localized(feed.message, feed.messageEn) || "";
    }

    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok && response.status !== 503) throw new Error(data?.error || data?.message || response.statusText);
      return data;
    }

    async function loadReadiness() {
      try { state.readiness = await fetchJson("/api/readiness"); }
      catch (error) { state.readiness = {ok: false}; }
    }

    async function loadFixtures() {
      const payload = await fetchJson("/api/featured-matches");
      const previousActiveId = state.activeId;
      state.fixtures = (payload.matches || []).slice().sort((a, b) => fixtureTimeValue(a) - fixtureTimeValue(b));
      state.feedStatus = payload.feedStatus || null;
      state.activeFixture = state.fixtures.find((fixture) => fixture.id === previousActiveId)
        || state.fixtures.find((fixture) => fixture.predictionAvailable && fixture.statusCode !== "FINISHED")
        || state.fixtures[0]
        || null;
      state.activeId = state.activeFixture?.id || null;
    }

    function setLoading(isLoading) {
      state.loading = isLoading;
      $("app").classList.toggle("loading", isLoading);
    }

    async function loadPrediction(fixture) {
      if (!fixture) return;
      renderMatchShell(fixture);
      if (!fixture.predictionAvailable || !fixture.predictionPayload) return;
      try {
        state.prediction = await fetchJson("/api/predict", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(fixture.predictionPayload),
        });
        renderPrediction(fixture, state.prediction);
      } catch (error) {
        $("verdictTitle").textContent = error.message;
      } finally {
        attachIcons();
      }
    }

    async function selectFixture(id) {
      const fixture = state.fixtures.find((item) => item.id === id);
      if (!fixture) return;
      state.activeId = id;
      state.activeFixture = fixture;
      renderFixtures();
      await loadPrediction(fixture);
    }

    function renderAll() {
      renderShellCopy();
      renderGlobalStatus();
      renderFixtures();
      if (state.activeFixture) {
        renderMatchShell(state.activeFixture);
        if (state.prediction && state.activeFixture.predictionAvailable) renderPrediction(state.activeFixture, state.prediction);
      }
      attachIcons();
    }

    async function boot() {
      if (state.loading) return;
      setLoading(true);
      try {
        await Promise.all([loadReadiness(), loadFixtures()]);
        state.lastUpdatedAt = new Date().toISOString();
        renderAll();
        await loadPrediction(state.activeFixture);
      } finally {
        setLoading(false);
        attachIcons();
      }
    }

    $("refreshButton").addEventListener("click", boot);
    $("languageToggle").addEventListener("click", () => {
      state.lang = state.lang === "zh" ? "en" : "zh";
      try { window.localStorage?.setItem("matchoracle.lang", state.lang); } catch (error) {}
      renderAll();
    });

    boot().catch((error) => {
      $("verdictTitle").textContent = error.message;
      setLoading(false);
    });

    window.setInterval(() => {
      if (document.hidden || state.loading) return;
      boot();
    }, AUTO_REFRESH_MS);
  </script>
</body>
</html>
"""
