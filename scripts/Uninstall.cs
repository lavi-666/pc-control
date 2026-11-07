using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("PC Control Uninstaller")]
[assembly: AssemblyProduct("PC Control")]
[assembly: AssemblyDescription("PC Control Safe Uninstaller and System State Rollback")]
[assembly: AssemblyCompany("PC Control")]
[assembly: AssemblyVersion("2.4.0.0")]
[assembly: AssemblyFileVersion("2.4.0.0")]

namespace PCControl
{
    #region Minimal Standalone JSON Parser & Serializer
    public class JsonValue
    {
        public enum JsonType { Null, Boolean, Number, String, Array, Object }
        public JsonType Type { get; set; }
        public object Raw { get; set; }

        public bool AsBool { get { return Raw is bool ? (bool)Raw : false; } }
        public string AsString { get { return Raw != null ? Raw.ToString() : null; } }
        public double AsNumber { get { return Raw is double ? (double)Raw : 0; } }
        public int AsInt { get { return Raw != null ? Convert.ToInt32(Raw) : 0; } }
        public List<JsonValue> AsList { get { return Raw as List<JsonValue>; } }
        public Dictionary<string, JsonValue> AsObject { get { return Raw as Dictionary<string, JsonValue>; } }

        public JsonValue this[string key]
        {
            get
            {
                if (Type == JsonType.Object && AsObject != null && AsObject.ContainsKey(key))
                    return AsObject[key];
                return null;
            }
            set
            {
                if (Type != JsonType.Object)
                {
                    Type = JsonType.Object;
                    Raw = new Dictionary<string, JsonValue>(StringComparer.OrdinalIgnoreCase);
                }
                AsObject[key] = value;
            }
        }

        public JsonValue this[int index]
        {
            get
            {
                if (Type == JsonType.Array && AsList != null && index >= 0 && index < AsList.Count)
                    return AsList[index];
                return null;
            }
        }

        public bool ContainsKey(string key)
        {
            return Type == JsonType.Object && AsObject != null && AsObject.ContainsKey(key);
        }

        public static JsonValue Null { get { return new JsonValue { Type = JsonType.Null, Raw = null }; } }
        public static JsonValue From(bool value) { return new JsonValue { Type = JsonType.Boolean, Raw = value }; }
        public static JsonValue From(int value) { return new JsonValue { Type = JsonType.Number, Raw = (double)value }; }
        public static JsonValue From(double value) { return new JsonValue { Type = JsonType.Number, Raw = value }; }
        public static JsonValue From(string value) { return value == null ? Null : new JsonValue { Type = JsonType.String, Raw = value }; }
        public static JsonValue NewObject() { return new JsonValue { Type = JsonType.Object, Raw = new Dictionary<string, JsonValue>(StringComparer.OrdinalIgnoreCase) }; }
        public static JsonValue NewArray() { return new JsonValue { Type = JsonType.Array, Raw = new List<JsonValue>() }; }

        public static JsonValue Parse(string json)
        {
            if (string.IsNullOrEmpty(json)) return null;
            int pos = 0;
            SkipWhitespace(json, ref pos);
            return ParseValue(json, ref pos);
        }

        private static void SkipWhitespace(string s, ref int p)
        {
            while (p < s.Length && (s[p] == ' ' || s[p] == '\t' || s[p] == '\r' || s[p] == '\n'))
                p++;
        }

        private static JsonValue ParseValue(string s, ref int p)
        {
            SkipWhitespace(s, ref p);
            if (p >= s.Length) return null;

            char c = s[p];
            if (c == '{') return ParseObject(s, ref p);
            if (c == '[') return ParseArray(s, ref p);
            if (c == '"') return ParseString(s, ref p);
            if (c == 't' || c == 'T' || c == 'f' || c == 'F') return ParseBoolean(s, ref p);
            if (c == 'n' || c == 'N') return ParseNull(s, ref p);
            if (c == '-' || (c >= '0' && c <= '9')) return ParseNumber(s, ref p);

            return null;
        }

        private static JsonValue ParseObject(string s, ref int p)
        {
            p++; // skip '{'
            var dict = new Dictionary<string, JsonValue>(StringComparer.OrdinalIgnoreCase);
            while (p < s.Length)
            {
                SkipWhitespace(s, ref p);
                if (p < s.Length && s[p] == '}') { p++; return new JsonValue { Type = JsonType.Object, Raw = dict }; }
                if (p < s.Length && s[p] == ',') { p++; continue; }

                JsonValue keyVal = ParseString(s, ref p);
                if (keyVal == null) break;
                string key = keyVal.AsString;

                SkipWhitespace(s, ref p);
                if (p < s.Length && s[p] == ':') p++;

                JsonValue val = ParseValue(s, ref p);
                dict[key] = val;

                SkipWhitespace(s, ref p);
                if (p < s.Length && s[p] == ',') p++;
            }
            return new JsonValue { Type = JsonType.Object, Raw = dict };
        }

        private static JsonValue ParseArray(string s, ref int p)
        {
            p++; // skip '['
            var list = new List<JsonValue>();
            while (p < s.Length)
            {
                SkipWhitespace(s, ref p);
                if (p < s.Length && s[p] == ']') { p++; return new JsonValue { Type = JsonType.Array, Raw = list }; }
                if (p < s.Length && s[p] == ',') { p++; continue; }

                JsonValue val = ParseValue(s, ref p);
                if (val != null) list.Add(val);

                SkipWhitespace(s, ref p);
                if (p < s.Length && s[p] == ',') p++;
            }
            return new JsonValue { Type = JsonType.Array, Raw = list };
        }

        private static JsonValue ParseString(string s, ref int p)
        {
            if (p >= s.Length || s[p] != '"') return null;
            p++; // skip quote
            var sb = new StringBuilder();
            while (p < s.Length)
            {
                char c = s[p++];
                if (c == '"') return new JsonValue { Type = JsonType.String, Raw = sb.ToString() };
                if (c == '\\' && p < s.Length)
                {
                    char esc = s[p++];
                    if (esc == '"') sb.Append('"');
                    else if (esc == '\\') sb.Append('\\');
                    else if (esc == '/') sb.Append('/');
                    else if (esc == 'b') sb.Append('\b');
                    else if (esc == 'f') sb.Append('\f');
                    else if (esc == 'n') sb.Append('\n');
                    else if (esc == 'r') sb.Append('\r');
                    else if (esc == 't') sb.Append('\t');
                    else if (esc == 'u' && p + 4 <= s.Length)
                    {
                        string hex = s.Substring(p, 4);
                        p += 4;
                        sb.Append((char)Convert.ToInt32(hex, 16));
                    }
                    else sb.Append(esc);
                }
                else sb.Append(c);
            }
            return new JsonValue { Type = JsonType.String, Raw = sb.ToString() };
        }

        private static JsonValue ParseBoolean(string s, ref int p)
        {
            if (p + 4 <= s.Length && string.Compare(s.Substring(p, 4), "true", true) == 0)
            {
                p += 4;
                return new JsonValue { Type = JsonType.Boolean, Raw = true };
            }
            if (p + 5 <= s.Length && string.Compare(s.Substring(p, 5), "false", true) == 0)
            {
                p += 5;
                return new JsonValue { Type = JsonType.Boolean, Raw = false };
            }
            return null;
        }

        private static JsonValue ParseNull(string s, ref int p)
        {
            if (p + 4 <= s.Length && string.Compare(s.Substring(p, 4), "null", true) == 0)
            {
                p += 4;
                return Null;
            }
            return null;
        }

        private static JsonValue ParseNumber(string s, ref int p)
        {
            int start = p;
            if (s[p] == '-') p++;
            while (p < s.Length && (char.IsDigit(s[p]) || s[p] == '.' || s[p] == 'e' || s[p] == 'E' || s[p] == '+' || s[p] == '-'))
            {
                if ((s[p] == '+' || s[p] == '-') && p > start && s[p - 1] != 'e' && s[p - 1] != 'E')
                    break;
                p++;
            }
            string numStr = s.Substring(start, p - start);
            double val;
            if (double.TryParse(numStr, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out val))
                return new JsonValue { Type = JsonType.Number, Raw = val };
            return null;
        }

        public override string ToString()
        {
            return ToJsonString(0);
        }

        public string ToJsonString(int indent)
        {
            var sb = new StringBuilder();
            SerializeValue(this, sb, indent, 0);
            return sb.ToString();
        }

        private static void SerializeValue(JsonValue v, StringBuilder sb, int indent, int depth)
        {
            if (v == null || v.Type == JsonType.Null) { sb.Append("null"); return; }
            if (v.Type == JsonType.Boolean) { sb.Append(v.AsBool ? "true" : "false"); return; }
            if (v.Type == JsonType.Number) { sb.Append(Convert.ToString(v.Raw, System.Globalization.CultureInfo.InvariantCulture)); return; }
            if (v.Type == JsonType.String)
            {
                sb.Append('"');
                foreach (char c in v.AsString)
                {
                    if (c == '"') sb.Append("\\\"");
                    else if (c == '\\') sb.Append("\\\\");
                    else if (c == '\b') sb.Append("\\b");
                    else if (c == '\f') sb.Append("\\f");
                    else if (c == '\n') sb.Append("\\n");
                    else if (c == '\r') sb.Append("\\r");
                    else if (c == '\t') sb.Append("\\t");
                    else if (c < 32) sb.AppendFormat("\\u{0:x4}", (int)c);
                    else sb.Append(c);
                }
                sb.Append('"');
                return;
            }
            if (v.Type == JsonType.Array)
            {
                var list = v.AsList;
                if (list == null || list.Count == 0) { sb.Append("[]"); return; }
                sb.Append('[');
                if (indent > 0) sb.AppendLine();
                for (int i = 0; i < list.Count; i++)
                {
                    if (indent > 0) sb.Append(new string(' ', (depth + 1) * indent));
                    SerializeValue(list[i], sb, indent, depth + 1);
                    if (i < list.Count - 1) sb.Append(',');
                    if (indent > 0) sb.AppendLine();
                }
                if (indent > 0) sb.Append(new string(' ', depth * indent));
                sb.Append(']');
                return;
            }
            if (v.Type == JsonType.Object)
            {
                var dict = v.AsObject;
                if (dict == null || dict.Count == 0) { sb.Append("{}"); return; }
                sb.Append('{');
                if (indent > 0) sb.AppendLine();
                int idx = 0;
                foreach (var kvp in dict)
                {
                    if (indent > 0) sb.Append(new string(' ', (depth + 1) * indent));
                    SerializeValue(JsonValue.From(kvp.Key), sb, 0, 0);
                    sb.Append(": ");
                    SerializeValue(kvp.Value, sb, indent, depth + 1);
                    if (idx < dict.Count - 1) sb.Append(',');
                    if (indent > 0) sb.AppendLine();
                    idx++;
                }
                if (indent > 0) sb.Append(new string(' ', depth * indent));
                sb.Append('}');
                return;
            }
        }
    }
    #endregion

    #region Operation Models and Journal Status
    public enum ConflictResolutionPolicy
    {
        Keep,       // Safe default: leave user's manual change untouched
        Restore     // Explicitly requested: force restoration to pre-install original
    }

    public class ComponentPlan
    {
        public string ComponentId;
        public string Category;
        public string Description;
        public bool ExistedBefore;
        public object OriginalValue;
        public object AppliedValue;
        public object CurrentValue;
        public bool HasConflict;
        public string PlannedAction;
        public string ExecutionResult;
    }

    public class UninstallOptions
    {
        public bool Silent = false;
        public bool DryRun = false;
        public string SandboxDir = null;
        public ConflictResolutionPolicy ConflictPolicy = ConflictResolutionPolicy.Keep;
        public bool KeepUserData = false;
        public string ReportFile = null;
        public bool NoSelfDelete = false;
        public bool RestoreSystemSettings = true;
        public bool RemoveShortcuts = true;
        public bool CleanLocalAppCache = true;
    }
    #endregion

    public static class UninstallerEngine
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AttachConsole(int dwProcessId);

        public static void EnsureConsoleOutput()
        {
            try
            {
                AttachConsole(-1);
                var stdOut = Console.OpenStandardOutput();
                if (stdOut != null && stdOut != Stream.Null)
                {
                    Console.SetOut(new StreamWriter(stdOut, new UTF8Encoding(false)) { AutoFlush = true });
                }
                var stdErr = Console.OpenStandardError();
                if (stdErr != null && stdErr != Stream.Null)
                {
                    Console.SetError(new StreamWriter(stdErr, new UTF8Encoding(false)) { AutoFlush = true });
                }
            }
            catch { }
        }

        public static bool IsAdministrator()
        {
            try
            {
                var identity = WindowsIdentity.GetCurrent();
                var principal = new WindowsPrincipal(identity);
                return principal.IsInRole(WindowsBuiltInRole.Administrator);
            }
            catch { return false; }
        }

        public static string ResolveBaseDir(UninstallOptions opts)
        {
            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                return Path.GetFullPath(opts.SandboxDir);
            }
            return Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/'));
        }

        public static JsonValue LoadJournal(string baseDir, UninstallOptions opts, out string journalStatus, out string journalPathUsed)
        {
            journalStatus = "missing";
            journalPathUsed = null;

            List<string> candidatePaths = new List<string>();
            candidatePaths.Add(Path.Combine(baseDir, "logs", "system_state_journal.json"));

            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                candidatePaths.Add(Path.Combine(opts.SandboxDir, "localappdata", "PCControl", "system_state_journal.json"));
            }
            else
            {
                string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                if (!string.IsNullOrEmpty(localApp))
                {
                    candidatePaths.Add(Path.Combine(localApp, "PCControl", "system_state_journal.json"));
                }
            }

            foreach (string path in candidatePaths)
            {
                if (File.Exists(path))
                {
                    journalPathUsed = path;
                    try
                    {
                        string content = File.ReadAllText(path, Encoding.UTF8);
                        JsonValue parsed = JsonValue.Parse(content);
                        if (parsed != null && parsed.Type == JsonValue.JsonType.Object && parsed.ContainsKey("entries"))
                        {
                            journalStatus = "ok";
                            return parsed;
                        }
                        journalStatus = "corrupted";
                    }
                    catch
                    {
                        journalStatus = "corrupted";
                    }
                }
            }

            return null;
        }

        #region Mock / Real System Accessors
        private static string GetSandboxStateFile(string sandboxDir)
        {
            return Path.Combine(sandboxDir, "mock_windows_state.json");
        }

        public static JsonValue LoadSandboxState(string sandboxDir)
        {
            string file = GetSandboxStateFile(sandboxDir);
            if (File.Exists(file))
            {
                try
                {
                    return JsonValue.Parse(File.ReadAllText(file, Encoding.UTF8));
                }
                catch { }
            }
            var root = JsonValue.NewObject();
            root["registry"] = JsonValue.NewObject();
            root["firewall_rules"] = JsonValue.NewObject();
            root["shortcuts"] = JsonValue.NewObject();
            return root;
        }

        public static void SaveSandboxState(string sandboxDir, JsonValue state)
        {
            string file = GetSandboxStateFile(sandboxDir);
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            File.WriteAllText(file, state.ToJsonString(2), new UTF8Encoding(false));
        }

        public static bool QueryRegistryDword(string hive, string subkey, string valName, UninstallOptions opts, out bool keyExists, out bool valExists, out int value)
        {
            keyExists = false;
            valExists = false;
            value = 0;

            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                var sbState = LoadSandboxState(opts.SandboxDir);
                string fullKey = hive + "\\" + subkey;
                if (sbState["registry"] != null && sbState["registry"].ContainsKey(fullKey))
                {
                    var kObj = sbState["registry"][fullKey];
                    keyExists = kObj["key_exists"] != null && kObj["key_exists"].AsBool;
                    if (kObj["values"] != null && kObj["values"].ContainsKey(valName))
                    {
                        valExists = true;
                        value = kObj["values"][valName].AsInt;
                        return true;
                    }
                }
                return keyExists;
            }

            try
            {
                RegistryKey root = hive.ToUpper() == "HKLM" ? Registry.LocalMachine : Registry.CurrentUser;
                using (RegistryKey k = root.OpenSubKey(subkey, false))
                {
                    if (k == null) return false;
                    keyExists = true;
                    object obj = k.GetValue(valName, null);
                    if (obj != null)
                    {
                        valExists = true;
                        value = Convert.ToInt32(obj);
                        return true;
                    }
                }
            }
            catch { }
            return keyExists;
        }

        public static void SetRegistryDword(string hive, string subkey, string valName, int value, UninstallOptions opts)
        {
            if (opts.DryRun) return;

            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                var sbState = LoadSandboxState(opts.SandboxDir);
                string fullKey = hive + "\\" + subkey;
                if (sbState["registry"] == null) sbState["registry"] = JsonValue.NewObject();
                if (sbState["registry"][fullKey] == null) sbState["registry"][fullKey] = JsonValue.NewObject();
                sbState["registry"][fullKey]["key_exists"] = JsonValue.From(true);
                if (sbState["registry"][fullKey]["values"] == null) sbState["registry"][fullKey]["values"] = JsonValue.NewObject();
                sbState["registry"][fullKey]["values"][valName] = JsonValue.From(value);
                SaveSandboxState(opts.SandboxDir, sbState);
                return;
            }

            RegistryKey root = hive.ToUpper() == "HKLM" ? Registry.LocalMachine : Registry.CurrentUser;
            using (RegistryKey k = root.CreateSubKey(subkey))
            {
                if (k != null) k.SetValue(valName, value, RegistryValueKind.DWord);
            }
        }

        public static void DeleteRegistryValue(string hive, string subkey, string valName, UninstallOptions opts)
        {
            if (opts.DryRun) return;

            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                var sbState = LoadSandboxState(opts.SandboxDir);
                string fullKey = hive + "\\" + subkey;
                if (sbState["registry"] != null && sbState["registry"][fullKey] != null && sbState["registry"][fullKey]["values"] != null)
                {
                    if (sbState["registry"][fullKey]["values"].ContainsKey(valName))
                    {
                        sbState["registry"][fullKey]["values"].AsObject.Remove(valName);
                        SaveSandboxState(opts.SandboxDir, sbState);
                    }
                }
                return;
            }

            try
            {
                RegistryKey root = hive.ToUpper() == "HKLM" ? Registry.LocalMachine : Registry.CurrentUser;
                using (RegistryKey k = root.OpenSubKey(subkey, true))
                {
                    if (k != null) k.DeleteValue(valName, false);
                }
            }
            catch { }
        }

        public static bool QueryFirewallRuleExists(string ruleName, UninstallOptions opts)
        {
            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                var sbState = LoadSandboxState(opts.SandboxDir);
                return sbState["firewall_rules"] != null && sbState["firewall_rules"].ContainsKey(ruleName);
            }

            try
            {
                using (RegistryKey k = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules", false))
                {
                    if (k == null) return false;
                    string target = "|name=" + ruleName.ToLower() + "|";
                    foreach (string valName in k.GetValueNames())
                    {
                        object v = k.GetValue(valName);
                        if (v is string && ((string)v).ToLower().Contains(target))
                            return true;
                    }
                }
            }
            catch { }
            return false;
        }

        public static void DeleteFirewallRule(string ruleName, UninstallOptions opts)
        {
            if (opts.DryRun) return;

            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                var sbState = LoadSandboxState(opts.SandboxDir);
                if (sbState["firewall_rules"] != null && sbState["firewall_rules"].ContainsKey(ruleName))
                {
                    sbState["firewall_rules"].AsObject.Remove(ruleName);
                    SaveSandboxState(opts.SandboxDir, sbState);
                }
                return;
            }

            try
            {
                var psi = new ProcessStartInfo("netsh.exe", "advfirewall firewall delete rule name=\"" + ruleName + "\"");
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                using (var p = Process.Start(psi))
                {
                    if (p != null) p.WaitForExit(5000);
                }
            }
            catch { }
        }
        #endregion

        #region Process Management
        public static List<int> StopOwnedProcesses(string baseDir, UninstallOptions opts, Action<string> log)
        {
            var stoppedPids = new List<int>();
            int currentPid = Process.GetCurrentProcess().Id;

            if (opts.DryRun)
            {
                log("[DRY-RUN] Process check: inspecting processes belonging to " + baseDir);
                return stoppedPids;
            }

            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                log("[SANDBOX] Isolated mode: real system processes will not be killed.");
                return stoppedPids;
            }

            // Signal manual_stop so watchdog does not restart the server
            try
            {
                string logsDir = Path.Combine(baseDir, "logs");
                Directory.CreateDirectory(logsDir);
                File.WriteAllText(Path.Combine(logsDir, "manual_stop.flag"), "uninstall", Encoding.ASCII);
            }
            catch { }

            string normBase = baseDir.TrimEnd('\\', '/').ToLowerInvariant() + "\\";

            foreach (var proc in Process.GetProcesses())
            {
                if (proc.Id == currentPid) continue;
                bool isOwned = false;
                try
                {
                    string exePath = null;
                    try { exePath = proc.MainModule != null ? proc.MainModule.FileName : null; } catch { }

                    if (!string.IsNullOrEmpty(exePath))
                    {
                        string normExe = exePath.ToLowerInvariant();
                        if (normExe.StartsWith(normBase))
                        {
                            isOwned = true;
                        }
                    }

                    if (isOwned)
                    {
                        log("Stopping owned process: " + proc.ProcessName + " (PID " + proc.Id + ")");
                        try
                        {
                            proc.CloseMainWindow();
                            if (!proc.WaitForExit(2000))
                            {
                                proc.Kill();
                                proc.WaitForExit(3000);
                            }
                            stoppedPids.Add(proc.Id);
                        }
                        catch { }
                    }
                }
                catch { }
                finally
                {
                    try { proc.Dispose(); } catch { }
                }
            }

            return stoppedPids;
        }
        #endregion

        #region Plan Construction & Execution
        public static List<ComponentPlan> BuildPlan(string baseDir, JsonValue journal, string journalStatus, UninstallOptions opts, Action<string> log)
        {
            var plan = new List<ComponentPlan>();

            if (journalStatus != "ok" || journal == null || journal["entries"] == null)
            {
                log("WARNING: System state journal is " + journalStatus + ". Applying safe fallback mode.");
                // Fallback for Firewall rules unambiguously created by PC Control
                string[] ownedRules = new string[] { "PC Control Server", "PC Control WOL Relay", "PC Control Server (TCP 5000)" };
                foreach (string rName in ownedRules)
                {
                    bool exists = QueryFirewallRuleExists(rName, opts);
                    if (exists)
                    {
                        plan.Add(new ComponentPlan
                        {
                            ComponentId = "firewall." + rName.Replace(" ", "_").ToLower(),
                            Category = "firewall",
                            Description = "Правило брандмауэра Windows '" + rName + "'",
                            ExistedBefore = false,
                            OriginalValue = false,
                            AppliedValue = true,
                            CurrentValue = true,
                            HasConflict = false,
                            PlannedAction = "DELETE_RULE"
                        });
                    }
                }

                // Fallback for Startup shortcut
                string startupLnk;
                if (!string.IsNullOrEmpty(opts.SandboxDir))
                    startupLnk = Path.Combine(opts.SandboxDir, "startup", "PC_Control_Server.lnk");
                else
                    startupLnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup), "PC_Control_Server.lnk");

                if (File.Exists(startupLnk))
                {
                    plan.Add(new ComponentPlan
                    {
                        ComponentId = "shortcut.startup",
                        Category = "shortcut",
                        Description = "Ярлык автозапуска PC_Control_Server.lnk",
                        ExistedBefore = false,
                        OriginalValue = false,
                        AppliedValue = true,
                        CurrentValue = true,
                        HasConflict = false,
                        PlannedAction = "DELETE_SHORTCUT"
                    });
                }
                return plan;
            }

            var entries = journal["entries"].AsObject;
            foreach (var kvp in entries)
            {
                string compId = kvp.Key;
                var entry = kvp.Value;
                string cat = entry["category"] != null ? entry["category"].AsString : "system";
                string desc = entry["description"] != null ? entry["description"].AsString : compId;
                var orig = entry["original_state"];
                var appl = entry["applied_state"];

                var item = new ComponentPlan
                {
                    ComponentId = compId,
                    Category = cat,
                    Description = desc
                };

                if (cat == "registry")
                {
                    string hive = orig["hive"] != null ? orig["hive"].AsString : "HKLM";
                    string subkey = orig["subkey"] != null ? orig["subkey"].AsString : "";
                    string valName = orig["value_name"] != null ? orig["value_name"].AsString : "";
                    bool origKeyExisted = orig["key_existed"] != null && orig["key_existed"].AsBool;
                    bool origValExisted = orig["value_existed"] != null && orig["value_existed"].AsBool;
                    int origVal = orig["value"] != null && orig["value"].Type == JsonValue.JsonType.Number ? orig["value"].AsInt : -1;
                    int applVal = appl["value"] != null && appl["value"].Type == JsonValue.JsonType.Number ? appl["value"].AsInt : -1;

                    item.ExistedBefore = origValExisted;
                    item.OriginalValue = origValExisted ? (object)origVal : null;
                    item.AppliedValue = applVal;

                    bool curKeyExisted, curValExisted;
                    int curVal;
                    QueryRegistryDword(hive, subkey, valName, opts, out curKeyExisted, out curValExisted, out curVal);
                    item.CurrentValue = curValExisted ? (object)curVal : null;

                    if (!curValExisted && !origValExisted)
                    {
                        item.PlannedAction = "NONE";
                    }
                    else if (curValExisted && origValExisted && curVal == origVal)
                    {
                        item.PlannedAction = "NONE";
                    }
                    else if (curValExisted && curVal == applVal)
                    {
                        // Clean rollback
                        item.PlannedAction = origValExisted ? "RESTORE_DWORD" : "DELETE_VALUE";
                    }
                    else
                    {
                        // Conflict! Current setting was changed to something other than applied and original
                        item.HasConflict = true;
                        if (opts.ConflictPolicy == ConflictResolutionPolicy.Keep)
                        {
                            item.PlannedAction = "KEEP_CONFLICT";
                        }
                        else
                        {
                            item.PlannedAction = origValExisted ? "RESTORE_DWORD" : "DELETE_VALUE";
                        }
                    }
                }
                else if (cat == "firewall")
                {
                    string ruleName = orig["rule_name"] != null ? orig["rule_name"].AsString : "PC Control Server";
                    bool origExisted = orig["existed"] != null && orig["existed"].AsBool;
                    bool curExisted = QueryFirewallRuleExists(ruleName, opts);

                    item.ExistedBefore = origExisted;
                    item.OriginalValue = origExisted;
                    item.AppliedValue = true;
                    item.CurrentValue = curExisted;

                    if (!curExisted)
                    {
                        item.PlannedAction = "NONE";
                    }
                    else if (!origExisted)
                    {
                        item.PlannedAction = "DELETE_RULE";
                    }
                    else
                    {
                        item.PlannedAction = "NONE"; // Preserves pre-existing rule
                    }
                }
                else if (cat == "shortcut")
                {
                    string scPath = orig["shortcut_path"] != null ? orig["shortcut_path"].AsString : "";
                    bool origExisted = orig["existed"] != null && orig["existed"].AsBool;
                    bool curExisted = File.Exists(scPath);

                    item.ExistedBefore = origExisted;
                    item.OriginalValue = origExisted;
                    item.AppliedValue = true;
                    item.CurrentValue = curExisted;

                    if (curExisted && !origExisted)
                    {
                        item.PlannedAction = "DELETE_SHORTCUT";
                    }
                    else
                    {
                        item.PlannedAction = "NONE";
                    }
                }
                else if (cat == "wol_adapter")
                {
                    string nicName = orig["adapter_name"] != null ? orig["adapter_name"].AsString : "";
                    string nicDesc = orig["interface_description"] != null ? orig["interface_description"].AsString : "";
                    string origMagic = orig["wake_on_magic_packet"] != null ? orig["wake_on_magic_packet"].AsString : "0";
                    string origPattern = orig["wake_on_pattern"] != null ? orig["wake_on_pattern"].AsString : "0";
                    bool origArmed = orig["wake_armed"] != null && orig["wake_armed"].AsBool;

                    item.ExistedBefore = true;
                    item.OriginalValue = string.Format("Magic:{0}, Pattern:{1}, Armed:{2}", origMagic, origPattern, origArmed);
                    item.AppliedValue = "Magic:1, Pattern:1, Armed:True";
                    item.CurrentValue = "Active";

                    item.PlannedAction = "RESTORE_WOL_ADAPTER";
                }

                plan.Add(item);
            }

            return plan;
        }

        public static void ExecutePlan(List<ComponentPlan> plan, JsonValue journal, string baseDir, UninstallOptions opts, Action<string> log)
        {
            foreach (var item in plan)
            {
                if (item.PlannedAction == "NONE")
                {
                    item.ExecutionResult = "UNCHANGED";
                    log("Component [" + item.ComponentId + "] left unchanged.");
                    continue;
                }

                if (item.PlannedAction == "KEEP_CONFLICT")
                {
                    item.ExecutionResult = "CONFLICT_KEPT";
                    log("CONFLICT DETECTED for [" + item.ComponentId + "]! User modified setting after install. Kept unchanged per safety policy.");
                    continue;
                }

                if (item.Category == "registry" && opts.RestoreSystemSettings)
                {
                    var orig = journal != null && journal["entries"] != null && journal["entries"][item.ComponentId] != null
                        ? journal["entries"][item.ComponentId]["original_state"] : null;
                    string hive = orig != null && orig["hive"] != null ? orig["hive"].AsString : "HKLM";
                    string subkey = orig != null && orig["subkey"] != null ? orig["subkey"].AsString : "";
                    string valName = orig != null && orig["value_name"] != null ? orig["value_name"].AsString : "";

                    if (item.PlannedAction == "RESTORE_DWORD" && orig != null)
                    {
                        int origVal = orig["value"].AsInt;
                        log("Restoring registry [" + hive + "\\" + subkey + "\\" + valName + "] to original value: " + origVal);
                        SetRegistryDword(hive, subkey, valName, origVal, opts);
                        item.ExecutionResult = item.HasConflict ? "CONFLICT_RESTORED" : "RESTORED";
                    }
                    else if (item.PlannedAction == "DELETE_VALUE")
                    {
                        log("Removing registry value [" + hive + "\\" + subkey + "\\" + valName + "] created by application.");
                        DeleteRegistryValue(hive, subkey, valName, opts);
                        item.ExecutionResult = item.HasConflict ? "CONFLICT_RESTORED" : "RESTORED";
                    }
                }
                else if (item.Category == "firewall" && opts.RestoreSystemSettings)
                {
                    string ruleName = "PC Control Server";
                    if (journal != null && journal["entries"] != null && journal["entries"][item.ComponentId] != null)
                    {
                        var orig = journal["entries"][item.ComponentId]["original_state"];
                        if (orig != null && orig["rule_name"] != null) ruleName = orig["rule_name"].AsString;
                    }
                    else if (item.ComponentId.Contains("wol_relay")) ruleName = "PC Control WOL Relay";

                    log("Deleting firewall rule: " + ruleName);
                    DeleteFirewallRule(ruleName, opts);
                    item.ExecutionResult = "RULE_REMOVED";
                }
                else if (item.Category == "shortcut" && opts.RemoveShortcuts)
                {
                    string scPath = null;
                    if (journal != null && journal["entries"] != null && journal["entries"][item.ComponentId] != null)
                    {
                        var orig = journal["entries"][item.ComponentId]["original_state"];
                        if (orig != null && orig["shortcut_path"] != null) scPath = orig["shortcut_path"].AsString;
                    }
                    if (string.IsNullOrEmpty(scPath))
                    {
                        if (!string.IsNullOrEmpty(opts.SandboxDir))
                            scPath = Path.Combine(opts.SandboxDir, "startup", "PC_Control_Server.lnk");
                        else
                            scPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup), "PC_Control_Server.lnk");
                    }

                    if (File.Exists(scPath))
                    {
                        log("Removing shortcut: " + scPath);
                        if (!opts.DryRun)
                        {
                            try { File.Delete(scPath); } catch (Exception ex) { log("Shortcut delete warning: " + ex.Message); }
                        }
                    }
                    item.ExecutionResult = "SHORTCUT_REMOVED";
                }
                else if (item.PlannedAction == "RESTORE_WOL_ADAPTER" && opts.RestoreSystemSettings)
                {
                    var entry = journal != null && journal["entries"] != null && journal["entries"][item.ComponentId] != null
                        ? journal["entries"][item.ComponentId] : null;
                    if (entry != null && entry["original_state"] != null)
                    {
                        var orig = entry["original_state"];
                        string nicName = orig["adapter_name"] != null ? orig["adapter_name"].AsString : "";
                        string nicDesc = orig["interface_description"] != null ? orig["interface_description"].AsString : "";
                        string origMagic = orig["wake_on_magic_packet"] != null ? orig["wake_on_magic_packet"].AsString : "0";
                        string origPattern = orig["wake_on_pattern"] != null ? orig["wake_on_pattern"].AsString : "0";
                        bool origArmed = orig["wake_armed"] != null && orig["wake_armed"].AsBool;

                        log("Restoring network adapter WOL settings for: " + nicName);
                        RestoreWolAdapter(nicName, nicDesc, origMagic, origPattern, origArmed, opts, log);
                        item.ExecutionResult = "ADAPTER_RESTORED";
                    }
                }
            }
        }

        public static void RunPowerShell(string script)
        {
            try
            {
                var psi = new ProcessStartInfo("powershell.exe", "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command \"" + script.Replace("\"", "\\\"") + "\"")
                {
                    CreateNoWindow = true,
                    UseShellExecute = false,
                    WindowStyle = ProcessWindowStyle.Hidden
                };
                var p = Process.Start(psi);
                if (p != null) p.WaitForExit(5000);
            }
            catch { }
        }

        public static void RestoreWolAdapter(string nicName, string nicDesc, string origMagic, string origPattern, bool origArmed, UninstallOptions opts, Action<string> log)
        {
            if (opts.DryRun)
            {
                log(string.Format("[DRY-RUN] Restore adapter '{0}': WakeOnMagicPacket={1}, WakeOnPattern={2}, WakeArmed={3}", nicName, origMagic, origPattern, origArmed));
                return;
            }

            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                string mockFile = Path.Combine(opts.SandboxDir, "mock_windows_state.json");
                try
                {
                    if (File.Exists(mockFile))
                    {
                        var state = JsonValue.Parse(File.ReadAllText(mockFile, Encoding.UTF8));
                        if (state != null && state["wol_adapters"] != null)
                        {
                            var adapters = state["wol_adapters"].AsObject;
                            if (adapters.ContainsKey(nicName))
                            {
                                adapters[nicName]["WakeOnMagicPacket"] = JsonValue.From(origMagic);
                                adapters[nicName]["WakeOnPattern"] = JsonValue.From(origPattern);
                                adapters[nicName]["wake_armed"] = JsonValue.From(origArmed);
                                File.WriteAllText(mockFile, state.ToString(), new UTF8Encoding(false));
                            }
                        }
                    }
                }
                catch { }
                log(string.Format("Restored sandbox WOL adapter '{0}' to original state.", nicName));
                return;
            }

            try
            {
                if (origMagic != "1")
                {
                    RunPowerShell(string.Format("Set-NetAdapterAdvancedProperty -Name '{0}' -RegistryKeyword '*WakeOnMagicPacket' -RegistryValue '{1}' -ErrorAction SilentlyContinue", nicName, origMagic));
                }
                if (origPattern != "1")
                {
                    RunPowerShell(string.Format("Set-NetAdapterAdvancedProperty -Name '{0}' -RegistryKeyword '*WakeOnPattern' -RegistryValue '{1}' -ErrorAction SilentlyContinue", nicName, origPattern));
                }
                if (!origArmed && !string.IsNullOrEmpty(nicDesc))
                {
                    var psi = new ProcessStartInfo("powercfg", string.Format("/devicedisablewake \"{0}\"", nicDesc))
                    {
                        CreateNoWindow = true,
                        UseShellExecute = false
                    };
                    Process.Start(psi);
                }
                log(string.Format("Restored network adapter '{0}' Wake-on-LAN and powercfg settings.", nicName));
            }
            catch (Exception ex)
            {
                log("Warning restoring network adapter: " + ex.Message);
            }
        }

        public static void CleanAppDataAndFiles(string baseDir, UninstallOptions opts, Action<string> log)
        {
            if (opts.DryRun)
            {
                log("[DRY-RUN] Directory cleanup: would clean local app cache and project directory files.");
                return;
            }

            // 1. Clean LocalAppData
            if (opts.CleanLocalAppCache)
            {
                string localApp;
                if (!string.IsNullOrEmpty(opts.SandboxDir))
                    localApp = Path.Combine(opts.SandboxDir, "localappdata", "PCControl");
                else
                    localApp = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PCControl");

                if (Directory.Exists(localApp))
                {
                    log("Cleaning browser profiles and cache in: " + localApp);
                    try
                    {
                        Directory.Delete(localApp, true);
                    }
                    catch (Exception ex)
                    {
                        log("Warning cleaning LocalAppData: " + ex.Message);
                    }
                }
            }

            // 2. Clean mock registration if in sandbox mode
            if (!string.IsNullOrEmpty(opts.SandboxDir))
            {
                string mockReg = Path.Combine(opts.SandboxDir, "mock_uninstall_reg.json");
                if (File.Exists(mockReg)) { try { File.Delete(mockReg); } catch { } }

                // Если baseDir не находится внутри песочницы (например, запуск Uninstall.exe из каталога репозитория для юнит-тестов),
                // не производим удаление файлов рабочего каталога репозитория!
                string fullBase = Path.GetFullPath(baseDir).TrimEnd('\\', '/');
                string fullSandbox = Path.GetFullPath(opts.SandboxDir).TrimEnd('\\', '/');
                if (!fullBase.StartsWith(fullSandbox, StringComparison.OrdinalIgnoreCase))
                {
                    log("Sandbox mode: baseDir is outside sandbox directory, skipping application files deletion.");
                    return;
                }
            }
            else
            {
                // Clean Windows Add/Remove Programs registration
                try
                {
                    string uninstSubkey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\PC Control";
                    Registry.CurrentUser.DeleteSubKeyTree(uninstSubkey, false);
                    Registry.LocalMachine.DeleteSubKeyTree(uninstSubkey, false);
                }
                catch { }

                // Clean Start Menu shortcuts
                try
                {
                    string startMenu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "PC Control");
                    if (Directory.Exists(startMenu)) Directory.Delete(startMenu, true);
                }
                catch { }
            }

            if (string.IsNullOrEmpty(baseDir) || !Directory.Exists(baseDir))
            {
                return;
            }

            log("Cleaning application directory files in " + baseDir);
            string selfExe = Process.GetCurrentProcess().MainModule.FileName;
            string manifestPath = Path.Combine(baseDir, "install_manifest.json");

            // Проверяем наличие install_manifest.json
            bool manifestHandled = false;
            if (File.Exists(manifestPath))
            {
                try
                {
                    string json = File.ReadAllText(manifestPath, Encoding.UTF8);
                    var manifest = JsonValue.Parse(json);
                    if (manifest != null && manifest["files"] != null && manifest["files"].AsList != null)
                    {
                        log("Using verified installation manifest to safely delete only installed files.");
                        var filesList = manifest["files"].AsList;
                        var dirSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

                        foreach (var fItem in filesList)
                        {
                            if (fItem == null) continue;
                            string rel = fItem["path"] != null ? fItem["path"].AsString : null;
                            if (string.IsNullOrWhiteSpace(rel)) continue;

                            string fullPath = Path.Combine(baseDir, rel.Replace('/', '\\'));

                            // Защита пользовательских данных
                            if (opts.KeepUserData)
                            {
                                string fName = Path.GetFileName(fullPath);
                                if (fName.Equals("config.json", StringComparison.OrdinalIgnoreCase) ||
                                    fName.Equals("launch_presets.json", StringComparison.OrdinalIgnoreCase) ||
                                    rel.StartsWith("logs", StringComparison.OrdinalIgnoreCase) ||
                                    rel.StartsWith("backups", StringComparison.OrdinalIgnoreCase) ||
                                    fName.EndsWith(".user.json", StringComparison.OrdinalIgnoreCase))
                                {
                                    log("Preserved user configuration: " + rel);
                                    continue;
                                }
                            }

                            if (string.Equals(fullPath, selfExe, StringComparison.OrdinalIgnoreCase))
                                continue;

                            if (File.Exists(fullPath))
                            {
                                try
                                {
                                    File.Delete(fullPath);
                                    string dir = Path.GetDirectoryName(fullPath);
                                    if (!string.Equals(dir, baseDir, StringComparison.OrdinalIgnoreCase))
                                        dirSet.Add(dir);
                                }
                                catch { }
                            }
                        }

                        // Удаляем директории проекта снизу вверх ТОЛЬКО если они пусты
                        var dirsSorted = new List<string>(dirSet);
                        dirsSorted.Sort((a, b) => b.Length.CompareTo(a.Length));
                        foreach (string d in dirsSorted)
                        {
                            try
                            {
                                if (Directory.Exists(d) && Directory.GetFileSystemEntries(d).Length == 0)
                                {
                                    Directory.Delete(d, false); // Без рекурсии!
                                }
                            }
                            catch { }
                        }

                        // Удаляем сам манифест
                        try { File.Delete(manifestPath); } catch { }
                        manifestHandled = true;
                    }
                }
                catch (Exception ex)
                {
                    log("Manifest parsing warning: " + ex.Message + ". Falling back to strict whitelist safety cleanup.");
                }
            }

            if (!manifestHandled)
            {
                // Fallback: манифест отсутствует или повреждён.
                // Строгий белый список: удаляются ИСКЛЮЧИТЕЛЬНО известные файлы PC Control!
                // Ни один посторонний файл или папка пользователя не будет затронут!
                log("Executing safe strict whitelist cleanup (foreign files will be completely preserved).");
                var knownRootFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
                {
                    "Launcher.exe", "Uninstall.exe", "unstaller.exe", "PC-Control-Setup.exe", "server.py", "open_app.pyw",
                    "pc_control.ico", "requirements.txt", "requirements-runtime.lock", "runtime-source.json",
                    "config.example.json", "README.md", "README.ru.md", "LICENSE", "START_HERE.txt",
                    "launcher.bat", "start_server.bat", "stop_server.bat", "change_password.bat", "uninstall.bat",
                    "release-manifest.json", "install_manifest.json", "PC_Control.apk", "PC-Control.apk", "watchdog.pyw"
                };

                if (!opts.KeepUserData)
                {
                    knownRootFiles.Add("config.json");
                    knownRootFiles.Add("launch_presets.json");
                }

                // Корневые файлы
                foreach (string fName in knownRootFiles)
                {
                    string fPath = Path.Combine(baseDir, fName);
                    if (string.Equals(fPath, selfExe, StringComparison.OrdinalIgnoreCase)) continue;
                    if (File.Exists(fPath))
                    {
                        try { File.Delete(fPath); } catch { }
                    }
                }

                // Проектные подпапки (только строго определённые)
                var projectSubdirs = new string[] { "web", "core", "modules", "scripts", "android_app", "tools", "runtime", "streamer_rs", "tests", "docs" };
                foreach (string sub in projectSubdirs)
                {
                    string subPath = Path.Combine(baseDir, sub);
                    if (Directory.Exists(subPath))
                    {
                        try
                        {
                            foreach (string subFile in Directory.GetFiles(subPath, "*.*", SearchOption.AllDirectories))
                            {
                                try { File.Delete(subFile); } catch { }
                            }
                            Directory.Delete(subPath, true);
                        }
                        catch { }
                    }
                }

                if (!opts.KeepUserData)
                {
                    string logsPath = Path.Combine(baseDir, "logs");
                    if (Directory.Exists(logsPath)) { try { Directory.Delete(logsPath, true); } catch { } }
                }
            }

            // Попытка удалить корневую директорию ТОЛЬКО ЕСЛИ ОНА ПОЛНОСТЬЮ ПУСТА
            try
            {
                if (Directory.Exists(baseDir) && Directory.GetFileSystemEntries(baseDir).Length == 0)
                {
                    Directory.Delete(baseDir, false);
                }
            }
            catch { }
        }

        public static void ScheduleSelfDeletion(string baseDir, UninstallOptions opts, Action<string> log)
        {
            if (opts.DryRun || opts.NoSelfDelete || !string.IsNullOrEmpty(opts.SandboxDir))
            {
                log("Self deletion skipped (dry-run, no-self-delete or sandbox mode active).");
                return;
            }

            try
            {
                string selfExe = Process.GetCurrentProcess().MainModule.FileName;
                // ВНИМАНИЕ: rmdir вызывается БЕЗ /s /q, чтобы исключить удаление непустой папки с чужими файлами!
                string cmdArgs = string.Format("/c ping 127.0.0.1 -n 3 >nul & del /f /q \"{0}\" & rmdir \"{1}\"", selfExe, baseDir);
                var psi = new ProcessStartInfo("cmd.exe", cmdArgs);
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                Process.Start(psi);
                log("Self-deletion scheduled via background task.");
            }
            catch (Exception ex)
            {
                log("Self deletion schedule failed: " + ex.Message);
            }
        }

        public static void GenerateReport(string reportFile, UninstallOptions opts, string baseDir, string journalStatus,
            List<int> stoppedPids, List<ComponentPlan> plan, List<string> logs)
        {
            if (string.IsNullOrEmpty(reportFile)) return;

            try
            {
                var report = JsonValue.NewObject();
                report["timestamp"] = JsonValue.From(DateTime.UtcNow.ToString("o"));
                report["application"] = JsonValue.From("PC Control Uninstaller");
                report["base_dir"] = JsonValue.From(baseDir);
                report["dry_run"] = JsonValue.From(opts.DryRun);
                report["sandbox"] = JsonValue.From(!string.IsNullOrEmpty(opts.SandboxDir));
                report["journal_status"] = JsonValue.From(journalStatus);
                report["conflict_policy"] = JsonValue.From(opts.ConflictPolicy.ToString().ToLower());

                var pidsArray = JsonValue.NewArray();
                foreach (int pid in stoppedPids) pidsArray.AsList.Add(JsonValue.From(pid));
                report["stopped_processes"] = pidsArray;

                var compsArray = JsonValue.NewArray();
                bool anyConflict = false;
                foreach (var item in plan)
                {
                    if (item.HasConflict) anyConflict = true;
                    var cObj = JsonValue.NewObject();
                    cObj["component_id"] = JsonValue.From(item.ComponentId);
                    cObj["category"] = JsonValue.From(item.Category);
                    cObj["description"] = JsonValue.From(item.Description);
                    cObj["existed_before"] = JsonValue.From(item.ExistedBefore);
                    cObj["has_conflict"] = JsonValue.From(item.HasConflict);
                    cObj["planned_action"] = JsonValue.From(item.PlannedAction);
                    cObj["execution_result"] = JsonValue.From(item.ExecutionResult);
                    compsArray.AsList.Add(cObj);
                }
                report["components"] = compsArray;
                report["conflicts_detected"] = JsonValue.From(anyConflict);

                var logArray = JsonValue.NewArray();
                foreach (string line in logs) logArray.AsList.Add(JsonValue.From(line));
                report["logs"] = logArray;

                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(reportFile)));
                File.WriteAllText(reportFile, report.ToJsonString(2), new UTF8Encoding(false));
            }
            catch { }
        }
        #endregion
    }

    #region WinForms GUI Dialog
    public class UninstallForm : Form
    {
        private UninstallOptions _opts;
        private string _baseDir;
        private TextBox _txtLogs;
        private ProgressBar _progBar;
        private Button _btnUninstall;
        private Button _btnDryRun;
        private Button _btnCancel;
        private CheckBox _chkRestoreSystem;
        private CheckBox _chkRemoveShortcuts;
        private CheckBox _chkCleanAppData;
        private CheckBox _chkKeepUserData;
        private Label _lblStatus;
        private List<string> _logLines = new List<string>();

        public UninstallForm(UninstallOptions opts)
        {
            _opts = opts;
            _baseDir = UninstallerEngine.ResolveBaseDir(_opts);
            InitializeComponents();
        }

        private void InitializeComponents()
        {
            Text = "PC Control — Деинсталляция и откат настроек";
            Size = new Size(720, 580);
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(15, 23, 42); // slate-900
            ForeColor = Color.FromArgb(248, 250, 252);
            Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;

            var titleLbl = new Label
            {
                Text = "PC Control — Полное удаление программы",
                Font = new Font("Segoe UI", 14f, FontStyle.Bold),
                ForeColor = Color.FromArgb(56, 189, 248), // sky-400
                Location = new Point(24, 18),
                AutoSize = true
            };
            Controls.Add(titleLbl);

            var subLbl = new Label
            {
                Text = "Программа корректно восстановит системные параметры Windows (реестр, брандмауэр),\n" +
                       "завершит фоновые процессы, удалит ярлыки и очистит временные профили.",
                Location = new Point(25, 52),
                Size = new Size(650, 36),
                ForeColor = Color.FromArgb(148, 163, 184) // slate-400
            };
            Controls.Add(subLbl);

            int optY = 96;
            _chkRestoreSystem = new CheckBox
            {
                Text = "Восстановить исходные параметры Windows (Windows Hello, брандмауэр, автозапуск)",
                Checked = true,
                Location = new Point(28, optY),
                AutoSize = true
            };
            Controls.Add(_chkRestoreSystem);

            _chkRemoveShortcuts = new CheckBox
            {
                Text = "Удалить ярлыки программы из автозагрузки и с рабочего стола",
                Checked = true,
                Location = new Point(28, optY + 28),
                AutoSize = true
            };
            Controls.Add(_chkRemoveShortcuts);

            _chkCleanAppData = new CheckBox
            {
                Text = "Очистить кэш и локальные профили (%LOCALAPPDATA%\\PCControl)",
                Checked = true,
                Location = new Point(28, optY + 56),
                AutoSize = true
            };
            Controls.Add(_chkCleanAppData);

            _chkKeepUserData = new CheckBox
            {
                Text = "Сохранить пользовательские настройки (config.json и пресеты запуска)",
                Checked = false,
                Location = new Point(28, optY + 84),
                AutoSize = true,
                ForeColor = Color.FromArgb(251, 191, 36) // amber-400
            };
            Controls.Add(_chkKeepUserData);

            _progBar = new ProgressBar
            {
                Location = new Point(28, optY + 120),
                Size = new Size(650, 16),
                Style = ProgressBarStyle.Continuous,
                Value = 0
            };
            Controls.Add(_progBar);

            _lblStatus = new Label
            {
                Text = "Готов к деинсталляции.",
                Location = new Point(28, optY + 142),
                Size = new Size(650, 20),
                ForeColor = Color.FromArgb(203, 213, 225)
            };
            Controls.Add(_lblStatus);

            _txtLogs = new TextBox
            {
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                BackColor = Color.FromArgb(30, 41, 59), // slate-800
                ForeColor = Color.FromArgb(226, 232, 240),
                Location = new Point(28, optY + 170),
                Size = new Size(650, 190),
                Font = new Font("Consolas", 9f)
            };
            Controls.Add(_txtLogs);

            int btnY = optY + 375;
            _btnUninstall = new Button
            {
                Text = "Удалить программу",
                Size = new Size(160, 36),
                Location = new Point(28, btnY),
                BackColor = Color.FromArgb(225, 29, 72), // rose-600
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _btnUninstall.FlatAppearance.BorderSize = 0;
            _btnUninstall.Click += (s, e) => RunUninstall(false);
            Controls.Add(_btnUninstall);

            _btnDryRun = new Button
            {
                Text = "Проверить (Dry Run)",
                Size = new Size(160, 36),
                Location = new Point(200, btnY),
                BackColor = Color.FromArgb(2, 132, 199), // sky-600
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _btnDryRun.FlatAppearance.BorderSize = 0;
            _btnDryRun.Click += (s, e) => RunUninstall(true);
            Controls.Add(_btnDryRun);

            _btnCancel = new Button
            {
                Text = "Отмена",
                Size = new Size(110, 36),
                Location = new Point(568, btnY),
                BackColor = Color.FromArgb(51, 65, 85),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _btnCancel.FlatAppearance.BorderSize = 0;
            _btnCancel.Click += (s, e) => Close();
            Controls.Add(_btnCancel);
        }

        private void AppendLog(string message)
        {
            string line = string.Format("[{0:HH:mm:ss}] {1}", DateTime.Now, message);
            _logLines.Add(line);
            if (InvokeRequired)
            {
                Invoke(new Action<string>(AppendLog), message);
                return;
            }
            _txtLogs.AppendText(line + Environment.NewLine);
        }

        private void RunUninstall(bool dryRun)
        {
            _btnUninstall.Enabled = false;
            _btnDryRun.Enabled = false;
            _chkRestoreSystem.Enabled = false;
            _chkRemoveShortcuts.Enabled = false;
            _chkCleanAppData.Enabled = false;
            _chkKeepUserData.Enabled = false;

            _opts.DryRun = dryRun;
            _opts.RestoreSystemSettings = _chkRestoreSystem.Checked;
            _opts.RemoveShortcuts = _chkRemoveShortcuts.Checked;
            _opts.CleanLocalAppCache = _chkCleanAppData.Checked;
            _opts.KeepUserData = _chkKeepUserData.Checked;

            var t = new Thread(() =>
            {
                try
                {
                    UpdateStatus("Чтение системного журнала...", 15);
                    string jStatus, jPath;
                    var journal = UninstallerEngine.LoadJournal(_baseDir, _opts, out jStatus, out jPath);
                    AppendLog("System state journal: " + jStatus + (jPath != null ? " (" + jPath + ")" : ""));

                    UpdateStatus("Проверка фоновых процессов...", 30);
                    var pids = UninstallerEngine.StopOwnedProcesses(_baseDir, _opts, AppendLog);

                    UpdateStatus("Построение плана отката настроек...", 50);
                    var plan = UninstallerEngine.BuildPlan(_baseDir, journal, jStatus, _opts, AppendLog);

                    // Check for conflicts
                    foreach (var item in plan)
                    {
                        if (item.HasConflict && !dryRun)
                        {
                            var res = MessageBox.Show(
                                "Обнаружен конфликт системных настроек:\n" +
                                item.Description + "\n\n" +
                                "Параметр был изменён вручную после работы программы.\n\n" +
                                "Нажмите 'Да' (рекомендуется), чтобы сохранить текущую настройку пользователя.\n" +
                                "Нажмите 'Нет', чтобы принудительно восстановить первоначальное значение Windows.",
                                "Конфликт системных параметров",
                                MessageBoxButtons.YesNo,
                                MessageBoxIcon.Question);

                            if (res == DialogResult.No)
                            {
                                item.PlannedAction = item.ExistedBefore ? "RESTORE_DWORD" : "DELETE_VALUE";
                            }
                        }
                    }

                    UpdateStatus("Выполнение отката настроек...", 70);
                    UninstallerEngine.ExecutePlan(plan, journal, _baseDir, _opts, AppendLog);

                    UpdateStatus("Очистка временных файлов и кэша...", 85);
                    UninstallerEngine.CleanAppDataAndFiles(_baseDir, _opts, AppendLog);

                    UninstallerEngine.GenerateReport(_opts.ReportFile, _opts, _baseDir, jStatus, pids, plan, _logLines);

                    UpdateStatus(dryRun ? "Проверка завершена без изменений." : "Деинсталляция успешно завершена!", 100);

                    if (!dryRun)
                    {
                        UninstallerEngine.ScheduleSelfDeletion(_baseDir, _opts, AppendLog);
                        MessageBox.Show("PC Control успешно удалён. Системные настройки восстановлены.", "PC Control", MessageBoxButtons.OK, MessageBoxIcon.Information);
                        Invoke(new Action(Close));
                    }
                    else
                    {
                        Invoke(new Action(() => {
                            _btnUninstall.Enabled = true;
                            _btnDryRun.Enabled = true;
                            _btnCancel.Text = "Закрыть";
                        }));
                    }
                }
                catch (Exception ex)
                {
                    AppendLog("ERROR: " + ex.Message);
                    UpdateStatus("Ошибка деинсталляции: " + ex.Message, 100);
                    Invoke(new Action(() => {
                        _btnUninstall.Enabled = true;
                        _btnDryRun.Enabled = true;
                    }));
                }
            });
            t.IsBackground = true;
            t.Start();
        }

        private void UpdateStatus(string text, int progress)
        {
            if (InvokeRequired)
            {
                Invoke(new Action<string, int>(UpdateStatus), text, progress);
                return;
            }
            _lblStatus.Text = text;
            _progBar.Value = Math.Min(100, Math.Max(0, progress));
        }
    }
    #endregion

    public static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            var opts = new UninstallOptions();

            // Check environment variable for sandbox
            string envSandbox = Environment.GetEnvironmentVariable("PC_CONTROL_SANDBOX_DIR");
            if (!string.IsNullOrEmpty(envSandbox))
            {
                opts.SandboxDir = envSandbox;
            }

            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i].ToLowerInvariant();
                if (a == "--silent" || a == "--headless" || a == "-s")
                {
                    opts.Silent = true;
                }
                else if (a == "--dry-run")
                {
                    opts.DryRun = true;
                }
                else if (a == "--no-self-delete")
                {
                    opts.NoSelfDelete = true;
                }
                else if (a == "--keep-user-data")
                {
                    opts.KeepUserData = true;
                }
                else if (a == "--sandbox-dir" && i + 1 < args.Length)
                {
                    opts.SandboxDir = args[++i];
                }
                else if (a == "--report-file" && i + 1 < args.Length)
                {
                    opts.ReportFile = args[++i];
                }
                else if (a == "--conflict-policy" && i + 1 < args.Length)
                {
                    string pol = args[++i].ToLowerInvariant();
                    if (pol == "restore") opts.ConflictPolicy = ConflictResolutionPolicy.Restore;
                    else opts.ConflictPolicy = ConflictResolutionPolicy.Keep;
                }
                else if (a == "--help" || a == "-h" || a == "/?")
                {
                    UninstallerEngine.EnsureConsoleOutput();
                    Console.WriteLine("PC Control Safe Uninstaller");
                    Console.WriteLine("Usage: Uninstall.exe [options]");
                    Console.WriteLine("  --silent, --headless      Run without GUI");
                    Console.WriteLine("  --dry-run                 Analyze and plan without changing system");
                    Console.WriteLine("  --sandbox-dir <path>      Run strictly inside isolated mock sandbox");
                    Console.WriteLine("  --conflict-policy <keep|restore> Conflict handling policy (default: keep)");
                    Console.WriteLine("  --keep-user-data          Preserve config.json and launch presets");
                    Console.WriteLine("  --report-file <path>      Output JSON uninstall execution report");
                    Console.WriteLine("  --no-self-delete          Do not schedule self-deletion");
                    return 0;
                }
            }

            // If running on real system without admin rights and not in sandbox, request elevation
            if (string.IsNullOrEmpty(opts.SandboxDir) && !UninstallerEngine.IsAdministrator())
            {
                try
                {
                    var psi = new ProcessStartInfo();
                    psi.FileName = Process.GetCurrentProcess().MainModule.FileName;
                    var sbArgs = new StringBuilder();
                    foreach (string arg in args)
                    {
                        if (arg.Contains(" ")) sbArgs.AppendFormat("\"{0}\" ", arg);
                        else sbArgs.AppendFormat("{0} ", arg);
                    }
                    psi.Arguments = sbArgs.ToString().Trim();
                    psi.Verb = "runas";
                    psi.UseShellExecute = true;
                    Process.Start(psi);
                    return 0;
                }
                catch (Exception ex)
                {
                    if (!opts.Silent)
                    {
                        MessageBox.Show("Для восстановления системных параметров Windows требуются права администратора: " + ex.Message, "PC Control", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    }
                }
            }

            if (!opts.Silent)
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new UninstallForm(opts));
                return 0;
            }

            // Headless / CLI execution
            UninstallerEngine.EnsureConsoleOutput();
            var logLines = new List<string>();
            Action<string> log = msg => {
                string line = string.Format("[{0:HH:mm:ss}] {1}", DateTime.Now, msg);
                logLines.Add(line);
                Console.WriteLine(line);
            };

            log("Starting PC Control silent uninstaller...");
            string baseDir = UninstallerEngine.ResolveBaseDir(opts);
            log("Base directory: " + baseDir);
            if (!string.IsNullOrEmpty(opts.SandboxDir)) log("SANDBOX MODE: " + opts.SandboxDir);
            if (opts.DryRun) log("DRY-RUN MODE ENABLED");

            string journalStatus, journalPath;
            var journal = UninstallerEngine.LoadJournal(baseDir, opts, out journalStatus, out journalPath);
            log("Journal status: " + journalStatus + (journalPath != null ? " (" + journalPath + ")" : ""));

            var pids = UninstallerEngine.StopOwnedProcesses(baseDir, opts, log);
            var plan = UninstallerEngine.BuildPlan(baseDir, journal, journalStatus, opts, log);

            UninstallerEngine.ExecutePlan(plan, journal, baseDir, opts, log);
            UninstallerEngine.CleanAppDataAndFiles(baseDir, opts, log);

            UninstallerEngine.GenerateReport(opts.ReportFile, opts, baseDir, journalStatus, pids, plan, logLines);

            if (!opts.DryRun)
            {
                UninstallerEngine.ScheduleSelfDeletion(baseDir, opts, log);
            }

            log("Uninstallation complete.");
            return 0;
        }
    }
}
