import React, { useState, useEffect } from 'react';
import { Coffee, Sun, Moon, Calendar, Download, Trash2, RefreshCw } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

export default function App() {
  const [stats, setStats] = useState({ today_total: 0, morning_total: 0, evening_total: 0, month_total: 0 });
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchDashboardData = async () => {
    setLoading(true);
    try {
      const [resStats, resLogs] = await Promise.all([
        fetch(`${API_BASE}/api/dashboard/stats`),
        fetch(`${API_BASE}/api/dashboard/logs`)
      ]);
      setStats(await resStats.json());
      setLogs(await resLogs.json());
    } catch (err) {
      console.error("Failed to load dashboard data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 25000)//25s auto-refresh
    return () => clearInterval(interval);
  }, []);

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this entry?")) return;
    try {
      await fetch(`${API_BASE}/api/dashboard/logs/${id}`, { method: 'DELETE' });
      fetchDashboardData();
    } catch (err) {
      alert("Error deleting record");
    }
  };

  const handleExportCSV = () => {
    window.open(`${API_BASE}/api/dashboard/export-csv`, '_blank');
  };

  return (
    <div className="min-h-screen p-6 md:p-10 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
            <Coffee className="w-8 h-8 text-amber-500" />
            Tea Tracker Portal
          </h1>
          <p className="text-slate-400 mt-1">Enterprise Beverage Consumption & Reconciliation</p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchDashboardData}
            className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded-lg border border-slate-700 transition"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button 
            onClick={handleExportCSV}
            className="flex items-center gap-2 bg-amber-600 hover:bg-amber-500 text-white font-medium px-4 py-2 rounded-lg transition shadow-lg shadow-amber-900/20"
          >
            <Download className="w-4 h-4" />
            Export Monthly CSV
          </button>
        </div>
      </div>

      {/* Live Counter Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl">
          <div className="flex items-center justify-between text-slate-400">
            <span>Today's Total</span>
            <Coffee className="w-5 h-5 text-amber-500" />
          </div>
          <p className="text-3xl font-extrabold text-white mt-3">{stats.today_total} <span className="text-sm font-normal text-slate-400">cups</span></p>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl">
          <div className="flex items-center justify-between text-slate-400">
            <span>Morning Session</span>
            <Sun className="w-5 h-5 text-yellow-400" />
          </div>
          <p className="text-3xl font-extrabold text-white mt-3">{stats.morning_total} <span className="text-sm font-normal text-slate-400">cups</span></p>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl">
          <div className="flex items-center justify-between text-slate-400">
            <span>Evening Session</span>
            <Moon className="w-5 h-5 text-indigo-400" />
          </div>
          <p className="text-3xl font-extrabold text-white mt-3">{stats.evening_total} <span className="text-sm font-normal text-slate-400">cups</span></p>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl">
          <div className="flex items-center justify-between text-slate-400">
            <span>Month Cumulative</span>
            <Calendar className="w-5 h-5 text-emerald-400" />
          </div>
          <p className="text-3xl font-extrabold text-white mt-3">{stats.month_total} <span className="text-sm font-normal text-slate-400">cups</span></p>
        </div>
      </div>

      {/* Manual Correction Suite Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="p-5 border-b border-slate-800 flex justify-between items-center">
          <div>
            <h2 className="text-lg font-bold text-white">Manual Correction Suite</h2>
            <p className="text-sm text-slate-400">Audit logs and remove accidental double-entries</p>
          </div>
          <span className="text-xs bg-slate-800 text-slate-400 px-3 py-1 rounded-full border border-slate-700">
            {logs.length} Recent Logs
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-300">
            <thead className="bg-slate-950/60 text-slate-400 uppercase text-xs">
              <tr>
                <th className="py-3.5 px-5">Date</th>
                <th className="py-3.5 px-5">Staff / Telegram ID</th>
                <th className="py-3.5 px-5">Session</th>
                <th className="py-3.5 px-5">Count</th>
                <th className="py-3.5 px-5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {logs.map((log) => (
                <tr key={log.id} className="hover:bg-slate-800/40 transition">
                  <td className="py-3.5 px-5 font-mono text-slate-300">{log.date}</td>
                  <td className="py-3.5 px-5">
                    <span className="font-semibold text-white">{log.user_name}</span>
                    <span className="block text-xs text-slate-500 font-mono">{log.phone_number}</span>
                  </td>
                  <td className="py-3.5 px-5">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      log.session === 'morning' ? 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20' : 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20'
                    }`}>
                      {log.session === 'morning' ? <Sun className="w-3 h-3" /> : <Moon className="w-3 h-3" />}
                      {log.session.toUpperCase()}
                    </span>
                  </td>
                  <td className="py-3.5 px-5 font-bold text-white">{log.count}</td>
                  <td className="py-3.5 px-5 text-right">
                    <button
                      onClick={() => handleDelete(log.id)}
                      className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition"
                      title="Delete Entry"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr>
                  <td colSpan="5" className="text-center py-8 text-slate-500">
                    No consumption logs found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}