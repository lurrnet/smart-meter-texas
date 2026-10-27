import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Bar, BarChart, Brush, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis
} from "recharts";
import "./style.css";

async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function MetricCard({ title, value, subtitle, raw, tone = "green", symbol = "↗", unit = "kWh" }) {
  return (
    <article className={"metric-card metric-" + tone}>
      <div className="metric-top"><span className="metric-icon" aria-hidden="true">{symbol}</span><span className="metric-label">{title}</span></div>
      <strong>{raw ? (value ?? "—") : (value == null ? "—" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 }) + " " + unit)}</strong>
      {subtitle ? <small>{subtitle}</small> : null}
    </article>
  );
}

function Panel({ title, children, subtitle, className = "" }) {
  return <section className={"panel " + className}><div className="panel-heading"><div><h2>{title}</h2>{subtitle ? <p>{subtitle}</p> : null}</div></div>{children}</section>;
}

function App() {
  const [summary, setSummary] = useState({});
  const [daily, setDaily] = useState([]);
  const [usageRange, setUsageRange] = useState(30);
  const [zoom, setZoom] = useState({ startIndex: 0, endIndex: 29 });
  const [intervals, setIntervals] = useState([]);
  const [heatmap, setHeatmap] = useState([]);
  const [status, setStatus] = useState({});
  const [health, setHealth] = useState({});
  const [cost, setCost] = useState({});
  const [defaultRate, setDefaultRate] = useState({cents_per_kwh: "12.5", monthly_fixed_fee: "0"});
  const [rateSettingsMessage, setRateSettingsMessage] = useState("");
  const [weatherSettings, setWeatherSettings] = useState({mode: "zip", zip_code: "", latitude: "", longitude: "", needs_refresh: false});
  const [weatherSettingsMessage, setWeatherSettingsMessage] = useState("");
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [rates, setRates] = useState([]);
  const [costSeries, setCostSeries] = useState({ daily: [], monthly: [] });
  const [rateForm, setRateForm] = useState({
    start_date: "",
    end_date: "",
    cents_per_kwh: "",
    monthly_fixed_fee: "0",
    label: ""
  });
  const [weather, setWeather] = useState({});
  const [hvac, setHvac] = useState({});
  const [anomaly, setAnomaly] = useState({items: []});
  const [forecast, setForecast] = useState({});
  const [notifications, setNotifications] = useState({});
  const [notificationForm, setNotificationForm] = useState({anomaly_threshold: 3.5, automatic_alerts_enabled: false, discord_webhook_url: ""});
  const [notificationSaving, setNotificationSaving] = useState(false);
  const [notificationMessage, setNotificationMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [catchingUp, setCatchingUp] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState("overview");
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem("smt-theme");
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  async function load() {
    try {
      const results = await Promise.all([
        api("/api/summary"),
        api("/api/daily?days=" + usageRange),
        api("/api/intervals/latest"),
        api("/api/heatmap?days=7"),
        api("/api/sync/status"),
        api("/api/data-health"),
        api("/api/mvp2/cost"),
        api("/api/mvp2/rates"),
        api("/api/mvp2/cost-series"),
        api("/api/mvp2/weather"),
        api("/api/mvp2/hvac"),
        api("/api/mvp2/anomalies"),
        api("/api/mvp2/forecast"),
        api("/api/mvp2/notifications"),
        api("/api/mvp2/default-rate"),
        api("/api/mvp2/weather/settings")
      ]);
      setSummary(results[0]);
      setDaily(results[1]);
      setZoom({ startIndex: 0, endIndex: Math.max(0, results[1].length - 1) });
      setIntervals(results[2]);
      setHeatmap(results[3]);
      setStatus(results[4]);
      setHealth(results[5]);
      setCost(results[6]);
      setRates(results[7]);
      setCostSeries(results[8]);
      setWeather(results[9]);
      setHvac(results[10]);
      setAnomaly(results[11]);
      setForecast(results[12]);
      setNotifications(results[13]);
      setDefaultRate(results[14]);
      setWeatherSettings(results[15]);
      setNotificationForm(prev => ({...prev, anomaly_threshold: results[13].anomaly_threshold ?? 3.5, automatic_alerts_enabled: !!results[13].automatic_alerts_enabled}));
      setError("");
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => { load(); }, [usageRange]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("smt-theme", theme);
  }, [theme]);

  async function syncNow() {
    setBusy(true);
    try {
      await api("/api/sync", { method: "POST" });
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function repairGaps() {
    setCatchingUp(true);
    try {
      await api("/api/repair-gaps", { method: "POST" });
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setCatchingUp(false);
    }
  }

  async function catchUp() {
    setCatchingUp(true);
    try {
      await api("/api/sync/catch-up", { method: "POST" });
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setCatchingUp(false);
    }
  }

  async function addRatePeriod(event) {
    event.preventDefault();
    try {
      await api("/api/mvp2/rates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...rateForm,
          cents_per_kwh: Number(rateForm.cents_per_kwh),
          monthly_fixed_fee: Number(rateForm.monthly_fixed_fee || 0)
        })
      });
      setRateForm({ start_date: "", end_date: "", cents_per_kwh: "", monthly_fixed_fee: "0", label: "" });
      await load();
    } catch (err) {
      setError(String(err));
    }
  }

  async function removeRatePeriod(id) {
    try {
      await api("/api/mvp2/rates/" + id, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(String(err));
    }
  }

  async function saveDefaultRate(event) {
    event.preventDefault();
    setSettingsBusy(true);
    setRateSettingsMessage("");
    try {
      const updated = await api("/api/mvp2/default-rate", {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          cents_per_kwh: Number(defaultRate.cents_per_kwh),
          monthly_fixed_fee: Number(defaultRate.monthly_fixed_fee)
        })
      });
      setDefaultRate(updated);
      setRateSettingsMessage("Default rate saved. Historical rate periods were preserved.");
      await load();
    } catch (err) { setRateSettingsMessage("Unable to save default rate: " + String(err)); }
    finally { setSettingsBusy(false); }
  }

  async function saveWeatherLocation(event) {
    event.preventDefault();
    setSettingsBusy(true);
    setWeatherSettingsMessage("");
    try {
      const updated = await api("/api/mvp2/weather/settings", {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          mode: weatherSettings.mode,
          zip_code: weatherSettings.zip_code,
          latitude: weatherSettings.latitude,
          longitude: weatherSettings.longitude
        })
      });
      setWeatherSettings(updated);
      setWeatherSettingsMessage(updated.needs_refresh ? "Location saved. Refresh weather history for this location." : "Weather settings saved.");
      await load();
    } catch (err) { setWeatherSettingsMessage("Unable to save location: " + String(err)); }
    finally { setSettingsBusy(false); }
  }

  async function refreshWeather() {
    setBusy(true);
    try { await api("/api/mvp2/weather/refresh", { method: "POST" }); await load(); }
    catch (err) { setError(String(err)); } finally { setBusy(false); }
  }

  async function testNotification() {
    try {
      const result = await api("/api/mvp2/notifications/test", { method: "POST" });
      setNotificationMessage(result.message || (result.ok ? "Test delivered." : "Unable to deliver."));
    } catch (err) { setNotificationMessage("Unable to send test notification."); }
  }

  async function saveNotificationSettings(event) {
    event.preventDefault();
    setNotificationSaving(true);
    setNotificationMessage("");
    try {
      const payload = {
        anomaly_threshold: Number(notificationForm.anomaly_threshold),
        automatic_alerts_enabled: notificationForm.automatic_alerts_enabled,
      };
      if (notificationForm.discord_webhook_url.trim()) payload.discord_webhook_url = notificationForm.discord_webhook_url.trim();
      const saved = await api("/api/mvp2/notifications/settings", {
        method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
      });
      setNotifications(saved);
      setNotificationForm(prev => ({...prev, discord_webhook_url: ""}));
      setNotificationMessage("Settings saved.");
      const newAnomalies = await api("/api/mvp2/anomalies");
      setAnomaly(newAnomalies);
    } catch (err) { setNotificationMessage("Unable to save settings: " + String(err)); }
    finally { setNotificationSaving(false); }
  }

  async function removeNotificationWebhook() {
    if (!window.confirm("Remove Discord webhook and disable automatic alerts?")) return;
    setNotificationSaving(true);
    try {
      const saved = await api("/api/mvp2/notifications/settings", {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({clear_discord_webhook: true})
      });
      setNotifications(saved);
      setNotificationForm(prev => ({...prev, discord_webhook_url: "", automatic_alerts_enabled: false}));
      setNotificationMessage("Webhook removed. Automatic alerts disabled.");
    } catch (err) { setNotificationMessage("Unable to remove webhook: " + String(err)); }
    finally { setNotificationSaving(false); }
  }

  function handleUsageWheel(event) {
    if (daily.length < 2) return;
    event.preventDefault();
    const direction = event.deltaY > 0 ? 1 : -1;
    setZoom(current => {
      const start = Math.max(0, Math.min(current.startIndex, daily.length - 1));
      const end = Math.max(start, Math.min(current.endIndex, daily.length - 1));
      const width = end - start + 1;
      const step = Math.max(1, Math.round(width * 0.12));
      let nextStart = start;
      let nextEnd = end;
      if (direction < 0 && width > 7) {
        nextStart = Math.min(end - 6, start + step);
        nextEnd = Math.max(nextStart + 6, end - step);
      } else if (direction > 0) {
        nextStart = Math.max(0, start - step);
        nextEnd = Math.min(daily.length - 1, end + step);
      }
      return { startIndex: nextStart, endIndex: nextEnd };
    });
  }

  function resetZoom() {
    setZoom({ startIndex: 0, endIndex: Math.max(0, daily.length - 1) });
  }

  const recent7 = daily.slice(-7);
  const average7 = recent7.length ? recent7.reduce((total, item) => total + Number(item.kwh || 0), 0) / recent7.length : null;
  const dailyWithAverage = daily.map((item, index) => ({
    ...item,
    average: daily.slice(Math.max(0, index - 6), index + 1).reduce((total, day) => total + Number(day.kwh || 0), 0) / Math.min(7, index + 1)
  }));
  const groupedHeatmap = heatmap.reduce((acc, row) => {
    if (!acc[row.date]) acc[row.date] = [];
    acc[row.date].push(row);
    return acc;
  }, {});

  return (
    <main>
      <header className="app-header">
        <div>
          <h1><span className="brand-mark" aria-hidden="true">⌂</span> Smart Meter Texas</h1>
          <p>Home energy dashboard</p>
        </div>
        <div className="actions">
          <button
            className="secondary theme-toggle"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label="Toggle light and dark theme"
            title="Toggle light and dark theme"
          >
            {theme === "dark" ? "☀" : "☾"}
          </button>
          <button className="secondary" onClick={catchUp} disabled={busy || catchingUp}>
            {catchingUp ? "Catching up…" : "Catch Up to Latest"}
          </button>
          <button onClick={syncNow} disabled={busy || catchingUp}>
            {busy ? "Syncing…" : "Sync Now"}
          </button>
        </div>
      </header>

      <nav className="page-tabs" aria-label="Dashboard sections">
        {[
          ["overview", "⌂", "Overview"],
          ["health", "▤", "Data Health"],
          ["cost", "$", "Energy Cost"],
          ["weather", "☁", "Weather & HVAC"],
          ["anomalies", "♧", "Anomalies & Notifications"]
        ].map(([id, icon, label]) => (
          <button
            key={id}
            className={page === id ? "page-tab active" : "page-tab"}
            onClick={() => setPage(id)}
          >
            <span className="tab-icon" aria-hidden="true">{icon}</span>{label}
          </button>
        ))}
      </nav>

      {error ? <div className="error">{error}</div> : null}

      {page === "overview" && <>
      <section className="cards overview-cards">
        <MetricCard title="Latest Day Usage" value={summary.today} subtitle={summary.latest_date ? "Latest reading · " + summary.latest_date : "Waiting for meter data"} tone="green" symbol="ϟ" />
        <MetricCard title="This Month (MTD)" value={summary.month_to_date} subtitle="Month-to-date consumption" tone="blue" symbol="▣" />
        <MetricCard title="Estimated Cost (MTD)" value={cost.month_cost} subtitle="Based on configured rate periods" tone="amber" symbol="$" unit="" />
        <MetricCard title="Avg. Daily Usage (7 Days)" value={average7} subtitle="Trailing 7 recorded days" tone="purple" symbol="↗" />
      </section>

      <div className="overview-chart-grid">
        <Panel title="Daily Usage" subtitle="Total energy consumption per day" className="usage-panel">
          <div className="range-picker">
            {[[7, "7D"], [30, "30D"], [90, "90D"], [180, "6M"], [365, "1Y"], [0, "All"]].map(([value, label]) => (
              <button key={label} className={usageRange === value ? "range active" : "range"} onClick={() => setUsageRange(value)}>{label}</button>
            ))}
          </div>
          <div className="chart-toolbar">
            <span>Scroll to zoom · drag the timeline handles</span>
            <button className="secondary small" onClick={resetZoom}>Reset zoom</button>
          </div>
          <div className="usage-chart" onWheel={handleUsageWheel}>
            <ResponsiveContainer width="100%" height={310}>
              <BarChart data={dailyWithAverage} margin={{ top: 8, right: 4, bottom: 4, left: -12 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" minTickGap={26} tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} />
                <Tooltip />
                <Bar dataKey="kwh" name="Daily Usage (kWh)" fill="#4bc7a1" radius={[4, 4, 0, 0]} maxBarSize={28} />
                <Brush dataKey="date" height={24} travellerWidth={9} startIndex={zoom.startIndex} endIndex={zoom.endIndex} onChange={(range) => {
                  if (range && range.startIndex != null && range.endIndex != null) setZoom({ startIndex: range.startIndex, endIndex: range.endIndex });
                }} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel title="15-Minute Usage" subtitle="Latest day · detailed interval consumption" className="interval-panel">
          <ResponsiveContainer width="100%" height={355}>
            <LineChart data={intervals} margin={{ top: 8, right: 8, bottom: 4, left: -12 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="start_time" minTickGap={35} tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} />
              <Tooltip />
              <Line type="monotone" dataKey="kwh" stroke="#1684e9" strokeWidth={2.5} dot={false} name="kWh" />
            </LineChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      <Panel title="7-Day Heatmap" subtitle="15-minute usage patterns across the last 7 days" className="heatmap-panel">
        <div className="heat-legend">Lower usage <span className="heat-gradient" /> Higher usage</div>
        <div className="heatmap">
          {Object.entries(groupedHeatmap).sort(([a], [b]) => b.localeCompare(a)).map(([date, dayRows]) => (
            <div className="heat-row" key={date}>
              <span>{date}</span>
              <div style={{ gridTemplateColumns: `repeat(${Math.max(dayRows.length, 1)}, minmax(0, 1fr))` }}>
                {dayRows.map((row, index) => {
                  const intensity = Math.min(1, Number(row.kwh || 0) / 2);
                  return <i key={index} title={row.start_time + " · " + Number(row.kwh || 0).toFixed(3) + " kWh"} style={{ backgroundColor: `hsl(${110 + intensity * 96} 65% ${93 - intensity * 55}%)` }} />;
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="heat-axis"><span>12 AM</span><span>4 AM</span><span>8 AM</span><span>12 PM</span><span>4 PM</span><span>8 PM</span><span>12 AM</span></div>
      </Panel>

      </>}

      {page === "health" && <>
      <div className="page-heading">
        <div>
          <h2>Data Health</h2>
          <p>Monitor data completeness, gaps, and repair status across the full history.</p>
        </div>
      </div>
      <Panel title="Data Health">
        <div className="health-grid">
          <div><span>Status</span><strong className={health.status === "healthy" ? "good" : "warn"}>{health.status === "healthy" ? "Healthy" : "Needs attention"}</strong></div>
          <div><span>Coverage</span><strong>{Number(health.coverage_pct || 0).toFixed(2)}%</strong></div>
          <div><span>Date range</span><strong>{health.date_start && health.date_end ? health.date_start + " → " + health.date_end : "—"}</strong></div>
          <div><span>Complete days</span><strong>{health.complete_days ?? 0}</strong></div>
          <div><span>Missing days</span><strong>{health.missing_days ?? 0}</strong></div>
          <div><span>Incomplete days</span><strong>{health.incomplete_days ?? 0}</strong></div>
          <div><span>Missing intervals</span><strong>{health.missing_intervals ?? 0}</strong></div>
          <div><span>First problem</span><strong>{health.first_problem_date || "None"}</strong></div>
        </div>
        <div className="repair-row">
          <button className="secondary" onClick={repairGaps} disabled={busy || catchingUp || !health.first_problem_date}>
            {catchingUp ? "Repairing…" : "Repair Gaps"}
          </button>
        </div>
      </Panel>

      </>}

      {page === "cost" && <>
      <div className="page-heading">
        <div>
          <h2>Energy Cost & Monthly Forecast</h2>
          <p>Track estimated bill, configured electricity rate, and monthly usage projection.</p>
        </div>
      </div>
      <Panel title="Energy Cost & Monthly Forecast">
        <div className="health-grid">
          <div><span>Current electricity rate</span><strong>{Number(cost.rate?.cents_per_kwh || 0).toFixed(2)} ¢/kWh</strong></div>
          <div><span>Month-to-date cost</span><strong>$ {Number(cost.month_cost || 0).toFixed(2)}</strong></div>
          <div><span>Forecast usage</span><strong>{Number(forecast.forecast_kwh || 0).toFixed(1)} kWh</strong></div>
          <div><span>Forecast bill</span><strong>$ {Number(forecast.forecast_cost || 0).toFixed(2)}</strong></div>
        </div>
        <p className="note">{forecast.method || "Forecast becomes available after usage data is loaded."}</p>
      </Panel>

      <Panel title="Default Electricity Rate" subtitle="Used when no more specific rate period applies. Changes affect historical estimates for dates relying on this baseline.">
        <form className="settings-form" onSubmit={saveDefaultRate}>
          <label>Default rate (¢/kWh)
            <input type="number" min="0" max="1000" step="0.001" required
              value={defaultRate.cents_per_kwh}
              onChange={e => setDefaultRate(prev => ({...prev, cents_per_kwh: e.target.value}))} />
          </label>
          <label>Monthly fixed fee ($)
            <input type="number" min="0" max="100000" step="0.01" required
              value={defaultRate.monthly_fixed_fee}
              onChange={e => setDefaultRate(prev => ({...prev, monthly_fixed_fee: e.target.value}))} />
          </label>
          <button type="submit" disabled={settingsBusy}>Save Default Rate</button>
        </form>
        <p className="note">Your separate date-ranged tariff entries remain intact. The original .env values are only used to initialize a missing baseline.</p>
        {rateSettingsMessage ? <p className="note" role="status">{rateSettingsMessage}</p> : null}
      </Panel>

      <Panel title="Electricity Rate Periods">
        <form className="rate-form" onSubmit={addRatePeriod}>
          <label>
            <span>Start date</span>
            <input type="date" required value={rateForm.start_date} onChange={e => setRateForm({...rateForm, start_date: e.target.value})} />
          </label>
          <label>
            <span>End date</span>
            <input type="date" value={rateForm.end_date} onChange={e => setRateForm({...rateForm, end_date: e.target.value})} />
          </label>
          <label>
            <span>Rate (¢/kWh)</span>
            <input type="number" min="0" step="0.001" required value={rateForm.cents_per_kwh} onChange={e => setRateForm({...rateForm, cents_per_kwh: e.target.value})} />
          </label>
          <label>
            <span>Monthly fixed fee ($)</span>
            <input type="number" min="0" step="0.01" value={rateForm.monthly_fixed_fee} onChange={e => setRateForm({...rateForm, monthly_fixed_fee: e.target.value})} />
          </label>
          <label className="rate-label">
            <span>Label</span>
            <input type="text" placeholder="e.g. Summer 2026 plan" value={rateForm.label} onChange={e => setRateForm({...rateForm, label: e.target.value})} />
          </label>
          <button type="submit">Add Rate Period</button>
        </form>

        <div className="rate-table-wrap">
          <table className="rate-table">
            <thead>
              <tr><th>Label</th><th>Start</th><th>End</th><th>Rate</th><th>Fixed fee</th><th></th></tr>
            </thead>
            <tbody>
              {rates.map(rate => (
                <tr key={rate.id}>
                  <td>{rate.label || "—"}</td>
                  <td>{rate.start_date}</td>
                  <td>{rate.end_date || "Open-ended"}</td>
                  <td>{Number(rate.cents_per_kwh).toFixed(3)} ¢/kWh</td>
                  <td>$ {Number(rate.monthly_fixed_fee || 0).toFixed(2)}</td>
                  <td><button className="secondary small" type="button" onClick={() => removeRatePeriod(rate.id)}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note">If periods overlap, the period with the latest start date takes precedence for that day.</p>
      </Panel>

      <Panel title="Monthly Cost">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={costSeries.monthly || []}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" minTickGap={22} />
            <YAxis />
            <Tooltip formatter={(value) => ["$ " + Number(value).toFixed(2), "Cost"]} />
            <Bar dataKey="cost" fill="#2563eb" radius={[4,4,0,0]} />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="Daily Cost · Recent 90 Days">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={(costSeries.daily || []).slice(-90)}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" minTickGap={28} />
            <YAxis />
            <Tooltip formatter={(value) => ["$ " + Number(value).toFixed(2), "Cost"]} />
            <Line type="monotone" dataKey="cost" stroke="#16a34a" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </Panel>

      </>}

      {page === "weather" && <>
      <div className="page-heading">
        <div>
          <h2>Weather Correlation & HVAC Analysis</h2>
          <p>Explore temperature-driven usage and weather-normalized HVAC estimates.</p>
        </div>
      </div>
      <Panel title="Weather Location Settings" subtitle="Choose a US ZIP code or override it with precise latitude and longitude.">
        <form className="settings-form" onSubmit={saveWeatherLocation}>
          <label>Location source
            <select value={weatherSettings.mode} onChange={e => setWeatherSettings(prev => ({...prev, mode: e.target.value}))}>
              <option value="zip">US ZIP code</option>
              <option value="coordinates">Custom coordinates</option>
              <option value="none">Disable weather location</option>
            </select>
          </label>
          {weatherSettings.mode === "zip" ? <label>ZIP code
            <input type="text" inputMode="numeric" maxLength={5} pattern="[0-9]{5}" required
              value={weatherSettings.zip_code}
              onChange={e => setWeatherSettings(prev => ({...prev, zip_code: e.target.value}))} />
          </label> : null}
          {weatherSettings.mode === "coordinates" ? <>
            <label>Latitude
              <input type="number" min="-90" max="90" step="any" required
                value={weatherSettings.latitude}
                onChange={e => setWeatherSettings(prev => ({...prev, latitude: e.target.value}))} />
            </label>
            <label>Longitude
              <input type="number" min="-180" max="180" step="any" required
                value={weatherSettings.longitude}
                onChange={e => setWeatherSettings(prev => ({...prev, longitude: e.target.value}))} />
            </label>
          </> : null}
          <button type="submit" disabled={settingsBusy}>Save Weather Location</button>
        </form>
        {weatherSettings.needs_refresh ? <p className="note" role="status">Weather location changed. Refresh weather history before interpreting the correlation and HVAC charts.</p> : null}
        {weatherSettingsMessage ? <p className="note" role="status">{weatherSettingsMessage}</p> : null}
      </Panel>
      <Panel title="Weather Correlation & HVAC Analysis">
        <div className="health-grid">
          <div><span>Weather data</span><strong>{weather.configured ? "Configured" : "Not configured"}</strong></div>
          <div><span>Temp ↔ usage correlation</span><strong>{weather.correlation == null ? "—" : Number(weather.correlation).toFixed(3)}</strong></div>
          <div><span>Estimated non-HVAC baseline</span><strong>{Number(hvac.baseline_kwh || 0).toFixed(1)} kWh/day</strong></div>
          <div><span>Latest est. HVAC load</span><strong>{hvac.recent?.length ? Number(hvac.recent[hvac.recent.length - 1].estimated_hvac_kwh).toFixed(1) + " kWh" : "—"}</strong></div>
        </div>
        <div className="repair-row"><button className="secondary" onClick={refreshWeather} disabled={busy || settingsBusy || weatherSettings.mode === "none"}>Refresh Weather History</button></div>
        <p className="note">{hvac.method}</p>
        {weather.points?.length ? <ResponsiveContainer width="100%" height={260}>
          <LineChart data={weather.points}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" minTickGap={35} />
            <YAxis yAxisId="usage" />
            <YAxis yAxisId="temp" orientation="right" />
            <Tooltip />
            <Line yAxisId="usage" type="monotone" dataKey="kwh" stroke="#2563eb" dot={false} name="kWh" />
            <Line yAxisId="temp" type="monotone" dataKey="temp_mean_f" stroke="#dc2626" dot={false} name="Mean °F" />
          </LineChart>
        </ResponsiveContainer> : null}
      </Panel>

      </>}

      {page === "anomalies" && <>
      <div className="page-heading">
        <div>
          <h2>Usage Anomalies & Notifications</h2>
          <p>Review unusual usage patterns and notification connectivity.</p>
        </div>
      </div>
      <Panel title="Usage Anomalies & Notifications">
        <div className="health-grid">
          <div><span>Recent anomalies</span><strong>{anomaly.items?.length || 0}</strong></div>
          <div><span>90-day median</span><strong>{Number(anomaly.median_kwh || 0).toFixed(1)} kWh/day</strong></div>
          <div><span>Discord</span><strong>{notifications.discord_configured ? "Configured" : "Not configured"}</strong></div>
          <div><span>Anomaly threshold</span><strong>{notifications.anomaly_threshold || 3.5}</strong></div>
        </div>
        {anomaly.items?.length ? <div className="anomaly-list">{anomaly.items.map(x =>
          <div key={x.date}><strong>{x.date}</strong><span>{Number(x.kwh).toFixed(1)} kWh · {x.direction} · score {x.score}</span></div>
        )}</div> : <p className="note">No strong anomalies detected in the recent window.</p>}
        <p className="note">Modified Z-score = 0.6745 × (daily usage − reference median) / MAD. The detector compares the most recent 30 usage days against a reference history of up to 90 preceding days. Positive means higher use and negative means lower use; the absolute score must reach the threshold. A score is not a probability.</p>
      </Panel>
      <Panel title="Discord Notification Settings" subtitle="Save configuration without editing .env or restarting Docker">
        <form className="notification-form" onSubmit={saveNotificationSettings}>
          <div className="notification-field">
            <label htmlFor="discord-webhook">Discord Webhook URL</label>
            <input id="discord-webhook" type="password" autoComplete="off"
              placeholder={notifications.discord_configured ? "Webhook saved — enter a new URL to replace" : "https://discord.com/api/webhooks/..."}
              value={notificationForm.discord_webhook_url}
              onChange={e => setNotificationForm(prev => ({...prev, discord_webhook_url: e.target.value}))} />
            <small>Stored privately in local SQLite. Existing URL is never returned by the API. Leave blank to keep it unchanged.</small>
          </div>
          <div className="notification-field">
            <label htmlFor="anomaly-score">Anomaly threshold (Modified Z-score)</label>
            <input id="anomaly-score" type="number" min="1" max="10" step="0.1"
              value={notificationForm.anomaly_threshold}
              onChange={e => setNotificationForm(prev => ({...prev, anomaly_threshold: e.target.value}))} />
            <small>Default 3.5; lower values detect more deviations and may produce more alerts.</small>
          </div>
          <label className="notification-check">
            <input type="checkbox" checked={notificationForm.automatic_alerts_enabled}
              onChange={e => setNotificationForm(prev => ({...prev, automatic_alerts_enabled: e.target.checked}))} />
            Enable automatic Discord alerts after successful synchronization
          </label>
          <p className="note">Automatic alerts are opt-in and cover only the latest usage day if it is no more than two days old. A day is notified at most once. Old anomalies are not sent retroactively.</p>
          <div className="notification-actions">
            <button type="submit" disabled={notificationSaving}>Save Settings</button>
            <button type="button" className="secondary" disabled={notificationSaving || !notifications.discord_configured} onClick={testNotification}>Send Test</button>
            <button type="button" className="secondary" disabled={notificationSaving || !notifications.discord_configured} onClick={removeNotificationWebhook}>Remove Webhook</button>
          </div>
          {notificationMessage ? <p role="status" className="note">{notificationMessage}</p> : null}
          {notifications.last_notification_date ? <p className="note">Last anomaly alert: {notifications.last_notification_date}</p> : null}
        </form>
      </Panel>

      </>}

      <footer>
        Last successful sync: {status.last_successful_run_at
          ? new Date(status.last_successful_run_at).toLocaleString()
          : "No successful sync recorded yet"}
      </footer>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
