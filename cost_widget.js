/**
 * YJ Partners API Cost Widget v1.0
 * ================================
 * 모든 HTML 사이트에 삽입 가능한 플로팅 비용 모니터 위젯.
 *
 * 사용법:
 *   <script src="cost_widget.js"></script>
 *   또는 data-api-url 속성으로 서버 주소 지정:
 *   <script src="cost_widget.js" data-api-url="http://192.168.0.10:5050"></script>
 */
(function () {
  "use strict";

  // ── 설정 ──
  const SCRIPT_TAG = document.currentScript;
  const API_BASE =
    (SCRIPT_TAG && SCRIPT_TAG.getAttribute("data-api-url")) ||
    "http://localhost:5050";
  const REFRESH_INTERVAL = 15000; // 15초

  // ── CSS 주입 ──
  const STYLES = `
    #yj-cost-widget-btn {
      position: fixed; bottom: 20px; right: 20px; z-index: 99999;
      width: 52px; height: 52px; border-radius: 50%;
      background: linear-gradient(135deg, #6366f1, #a855f7);
      border: none; cursor: pointer; box-shadow: 0 4px 20px rgba(99,102,241,0.4);
      display: flex; align-items: center; justify-content: center;
      transition: transform 0.2s, box-shadow 0.2s;
      font-size: 22px; color: white;
    }
    #yj-cost-widget-btn:hover {
      transform: scale(1.1);
      box-shadow: 0 6px 28px rgba(99,102,241,0.6);
    }
    #yj-cost-panel {
      position: fixed; bottom: 82px; right: 20px; z-index: 99998;
      width: 340px; max-height: 520px;
      background: #0a0e1a; border: 1px solid #1f2937;
      border-radius: 16px; box-shadow: 0 8px 40px rgba(0,0,0,0.5);
      font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
      color: #e2e8f0; font-size: 13px;
      overflow: hidden; display: none;
      animation: yjSlideUp 0.25s ease-out;
    }
    @keyframes yjSlideUp {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    #yj-cost-panel.visible { display: block; }
    .yj-header {
      background: linear-gradient(135deg, #111827, #0a0e1a);
      padding: 16px 18px 12px; border-bottom: 1px solid #1f2937;
    }
    .yj-header h3 {
      margin: 0; font-size: 15px; font-weight: 800; color: #f9fafb;
    }
    .yj-header small {
      color: #6b7280; font-size: 11px;
    }
    .yj-body { padding: 14px 18px; overflow-y: auto; max-height: 400px; }
    .yj-card {
      background: #111827; border: 1px solid #1f2937;
      border-radius: 12px; padding: 14px 16px; margin-bottom: 10px;
    }
    .yj-card-label { font-size: 11px; color: #6b7280; font-weight: 700; margin-bottom: 4px; }
    .yj-card-value { font-size: 24px; font-weight: 900; color: #f9fafb; }
    .yj-card-sub { font-size: 12px; color: #9ca3af; margin-top: 2px; }
    .yj-budget-bar {
      background: #1f2937; border-radius: 6px; height: 8px;
      margin-top: 8px; overflow: hidden;
    }
    .yj-budget-fill {
      height: 100%; border-radius: 6px; transition: width 0.5s ease;
    }
    .yj-model-row {
      display: flex; justify-content: space-between; align-items: center;
      padding: 6px 0; border-bottom: 1px solid #111827;
    }
    .yj-model-name { font-size: 12px; color: #9ca3af; font-weight: 600; }
    .yj-model-cost { font-size: 12px; color: #e5e7eb; font-weight: 700; }
    .yj-status-dot {
      display: inline-block; width: 8px; height: 8px;
      border-radius: 50%; margin-right: 6px;
    }
    .yj-error {
      color: #ef4444; font-size: 12px; text-align: center;
      padding: 20px; opacity: 0.8;
    }
    .yj-refresh {
      text-align: center; padding: 8px;
      border-top: 1px solid #1f2937;
    }
    .yj-refresh small { color: #4b5563; font-size: 10px; }
  `;

  const styleEl = document.createElement("style");
  styleEl.textContent = STYLES;
  document.head.appendChild(styleEl);

  // ── HTML 구조 ──
  const btn = document.createElement("button");
  btn.id = "yj-cost-widget-btn";
  btn.innerHTML = "\u20A9"; // ₩ 기호
  btn.title = "API \uBE44\uC6A9 \uBAA8\uB2C8\uD130"; // API 비용 모니터

  const panel = document.createElement("div");
  panel.id = "yj-cost-panel";
  panel.innerHTML = `
    <div class="yj-header">
      <h3>API \uBE44\uC6A9 \uBAA8\uB2C8\uD130</h3>
      <small>YJ Partners \u2022 \uC2E4\uC2DC\uAC04 \uCD94\uC801</small>
    </div>
    <div class="yj-body" id="yj-cost-body">
      <div class="yj-error">\uB85C\uB529 \uC911...</div>
    </div>
    <div class="yj-refresh">
      <small id="yj-last-update">\uB300\uAE30 \uC911...</small>
    </div>
  `;

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  // ── 토글 ──
  let isOpen = false;
  btn.addEventListener("click", function () {
    isOpen = !isOpen;
    panel.classList.toggle("visible", isOpen);
    if (isOpen) fetchCostData();
  });

  // ── 데이터 패칭 ──
  let refreshTimer = null;

  async function fetchCostData() {
    const body = document.getElementById("yj-cost-body");
    const lastUpdate = document.getElementById("yj-last-update");

    try {
      const [summaryRes, modelsRes] = await Promise.all([
        fetch(API_BASE + "/api/cost/summary"),
        fetch(API_BASE + "/api/cost/models"),
      ]);

      if (!summaryRes.ok) throw new Error("API \uC751\uB2F5 \uC624\uB958");

      const summary = await summaryRes.json();
      const modelsData = await modelsRes.json();

      // 예산 바 색상
      const pct = summary.budget.used_pct;
      let barColor = "#22c55e"; // green
      if (pct >= 100) barColor = "#ef4444"; // red
      else if (pct >= 80) barColor = "#f59e0b"; // amber

      // 상태 점 색상
      const statusColor =
        summary.budget.status === "over"
          ? "#ef4444"
          : summary.budget.status === "warn"
          ? "#f59e0b"
          : "#22c55e";

      let html = "";

      // 오늘 비용 카드
      html += `
        <div class="yj-card" style="border-left: 3px solid #6366f1;">
          <div class="yj-card-label">\uC624\uB298 \uBE44\uC6A9</div>
          <div class="yj-card-value">\u20A9${Number(
            summary.today.krw
          ).toLocaleString()}</div>
          <div class="yj-card-sub">$${summary.today.usd.toFixed(4)} USD</div>
        </div>
      `;

      // 이번달 비용 + 예산 바
      html += `
        <div class="yj-card" style="border-left: 3px solid #a855f7;">
          <div class="yj-card-label">\uC774\uBC88\uB2EC \uB204\uC801</div>
          <div class="yj-card-value">\u20A9${Number(
            summary.monthly.krw
          ).toLocaleString()}</div>
          <div class="yj-card-sub">$${summary.monthly.usd.toFixed(4)} USD</div>
          <div class="yj-budget-bar">
            <div class="yj-budget-fill" style="width: ${Math.min(
              pct,
              100
            )}%; background: ${barColor};"></div>
          </div>
          <div class="yj-card-sub" style="margin-top: 6px;">
            <span class="yj-status-dot" style="background: ${statusColor};"></span>
            \uC608\uC0B0: ${pct}% (\u20A9${Number(
        summary.budget.limit_krw
      ).toLocaleString()} \uD55C\uB3C4)
          </div>
        </div>
      `;

      // 전체 누적
      html += `
        <div class="yj-card" style="border-left: 3px solid #14b8a6;">
          <div class="yj-card-label">\uC804\uCCB4 \uB204\uC801</div>
          <div class="yj-card-value" style="font-size: 20px;">\u20A9${Number(
            summary.alltime.krw
          ).toLocaleString()}</div>
          <div class="yj-card-sub">$${summary.alltime.usd.toFixed(
            4
          )} USD | \uD658\uC728: \u20A9${summary.exchange_rate.toLocaleString()}/USD</div>
        </div>
      `;

      // 모델별 분류
      if (modelsData.models && modelsData.models.length > 0) {
        html += `<div class="yj-card">
          <div class="yj-card-label">\uBAA8\uB378\uBCC4 \uBE44\uC6A9</div>`;
        modelsData.models.forEach(function (m) {
          const name = m.model.length > 25 ? m.model.substring(0, 25) + "..." : m.model;
          html += `
            <div class="yj-model-row">
              <span class="yj-model-name">${name}</span>
              <span class="yj-model-cost">\u20A9${Number(
                m.cost_krw
              ).toLocaleString()} <small style="color:#6b7280;">($${m.cost_usd.toFixed(
            4
          )})</small></span>
            </div>`;
        });
        html += `</div>`;
      }

      body.innerHTML = html;

      const now = new Date();
      lastUpdate.textContent =
        now.getHours().toString().padStart(2, "0") +
        ":" +
        now.getMinutes().toString().padStart(2, "0") +
        ":" +
        now.getSeconds().toString().padStart(2, "0") +
        " \uC5C5\uB370\uC774\uD2B8 | 15\uCD08\uB9C8\uB2E4 \uC790\uB3D9 \uC0C8\uB85C\uACE0\uCE68";

      // 버튼 색상 업데이트
      if (summary.budget.status === "over") {
        btn.style.background = "linear-gradient(135deg, #ef4444, #dc2626)";
      } else if (summary.budget.status === "warn") {
        btn.style.background = "linear-gradient(135deg, #f59e0b, #d97706)";
      } else {
        btn.style.background = "linear-gradient(135deg, #6366f1, #a855f7)";
      }
    } catch (err) {
      body.innerHTML = `
        <div class="yj-error">
          \u26A0\uFE0F \uC11C\uBC84 \uC5F0\uACB0 \uC2E4\uD328<br>
          <small>${API_BASE}</small><br><br>
          <small>cost_api.py \uC11C\uBC84\uAC00 \uC2E4\uD589 \uC911\uC778\uC9C0 \uD655\uC778\uD558\uC138\uC694.<br>
          python cost_api.py</small>
        </div>`;
      lastUpdate.textContent = "\uC5F0\uACB0 \uC2E4\uD328";
    }
  }

  // ── 자동 새로고침 ──
  setInterval(function () {
    if (isOpen) fetchCostData();
  }, REFRESH_INTERVAL);

  // 초기 로드
  fetchCostData();
})();
