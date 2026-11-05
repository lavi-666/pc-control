using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("PC Control")]
[assembly: AssemblyProduct("PC Control")]
[assembly: AssemblyDescription("PC Control Center Launcher")]
[assembly: AssemblyCompany("PC Control")]
[assembly: AssemblyVersion("2.0.1.0")]
[assembly: AssemblyFileVersion("2.0.1.0")]

static class Program
{
    static readonly int CONTROL_PORT = GetControlPort();

    static int GetControlPort()
    {
        int value;
        return int.TryParse(Environment.GetEnvironmentVariable("PC_CONTROL_PANEL_PORT"), out value)
            && value > 0 && value <= 65535 ? value : 5055;
    }

    static bool BootstrapRuntime(string baseDir)
    {
        string script = Path.Combine(baseDir, "scripts", "bootstrap_runtime.ps1");
        if (!File.Exists(script))
        {
            MessageBox.Show("Неполный архив: отсутствует scripts\\bootstrap_runtime.ps1. Скачайте полный ZIP.", "PC Control");
            return false;
        }
        Application.EnableVisualStyles();
        using (Form form = new Form())
        using (TextBox output = new TextBox())
        using (System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer())
        {
            form.Text = "PC Control — первоначальная подготовка";
            form.Width = 760;
            form.Height = 430;
            form.StartPosition = FormStartPosition.CenterScreen;
            output.Multiline = true;
            output.ReadOnly = true;
            output.ScrollBars = ScrollBars.Vertical;
            output.Dock = DockStyle.Fill;
            output.Text = "Загрузка компонентов приложения. Установка Python в Windows не требуется. Пожалуйста, подождите...";
            form.Controls.Add(output);
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
            info.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\" -BaseDir \"" + baseDir.TrimEnd('\\') + "\"";
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.WorkingDirectory = baseDir;
            try
            {
                using (Process process = Process.Start(info))
                {
                    if (process == null) return false;
                    bool success = false;
                    timer.Interval = 500;
                    timer.Tick += delegate {
                        try {
                            string log = Path.Combine(baseDir, "logs", "bootstrap.log");
                            if (File.Exists(log)) { output.Text = File.ReadAllText(log); output.SelectionStart = output.TextLength; output.ScrollToCaret(); }
                            if (process.HasExited) { success = process.ExitCode == 0; timer.Stop(); form.Close(); }
                        } catch (IOException) { }
                    };
                    form.FormClosing += delegate {
                        if (!process.HasExited) {
                            ProcessStartInfo kill = new ProcessStartInfo("taskkill.exe", "/PID " + process.Id + " /T /F");
                            kill.UseShellExecute = false; kill.CreateNoWindow = true;
                            using (Process killer = Process.Start(kill)) { if (killer != null) killer.WaitForExit(3000); }
                        }
                    };
                    timer.Start();
                    form.ShowDialog();
                    if (!success) MessageBox.Show("Подготовка не завершена. Проверьте подключение и запустите лаунчер снова. Подробности: logs\\bootstrap.log", "PC Control", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return success;
                }
            }
            catch (Exception ex) { MessageBox.Show("Не удалось подготовить компоненты: " + ex.Message, "PC Control"); return false; }
        }
    }

    [STAThread]
    static void Main(string[] args)
    {
        if (args.Length > 0 && (args[0] == "--check-update" || args[0] == "-u" || args[0] == "/update"))
        {
            CheckForUpdates(true);
            return;
        }
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string scriptPath = Path.Combine(baseDir, "scripts", "control_panel.py");

        if (!File.Exists(scriptPath))
        {
            MessageBox.Show("Файл 'scripts\\control_panel.py' не найден в папке программы.", "PC Control", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        // 1. Проверяем, запущен ли уже веб-сервер панели управления (порт 5055)
        if (IsPortOpen(CONTROL_PORT))
        {
            if (!IsOwnPanel(baseDir))
                MessageBox.Show("Порт панели занят другой программой или другой копией PC Control. Закройте её и повторите запуск.", "PC Control", MessageBoxButtons.OK, MessageBoxIcon.Error);
            else if (Array.IndexOf(args, "--no-browser") < 0)
                LaunchBrowser("http://127.0.0.1:" + CONTROL_PORT);
            return;
        }

        // 2. Ищем pythonw.exe для полностью бесшумного запуска без окна консоли
        string pythonwExe = Path.Combine(baseDir, "runtime", "pythonw.exe");
        if (!File.Exists(pythonwExe) && !BootstrapRuntime(baseDir)) return;
        if (!IsValidPython(pythonwExe))
        {
            MessageBox.Show("Встроенный Python повреждён или не запускается. Распакуйте полный ZIP заново в доступную для записи папку.", "PC Control", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = pythonwExe;
        psi.Arguments = "\"" + scriptPath + "\"";
        if (Array.IndexOf(args, "--no-browser") >= 0) psi.Arguments += " --no-browser";
        psi.WorkingDirectory = baseDir;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.WindowStyle = ProcessWindowStyle.Hidden;
        psi.EnvironmentVariables.Remove("PYTHONHOME");
        psi.EnvironmentVariables.Remove("PYTHONPATH");
        psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";

        try
        {
            using (Process child = Process.Start(psi))
            {
                for (int attempt = 0; attempt < 60; attempt++)
                {
                    if (IsOwnPanel(baseDir)) return;
                    if (child == null || child.HasExited) break;
                    System.Threading.Thread.Sleep(250);
                }
                MessageBox.Show("Панель не подтвердила запуск. Проверьте logs в папке приложения и доступность порта " + CONTROL_PORT, "PC Control", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show("Ошибка при запуске панели управления:\n" + ex.Message, "PC Control", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    static bool IsOwnPanel(string baseDir)
    {
        try
        {
            string identity;
            using (SHA256 hash = SHA256.Create())
                identity = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(baseDir).TrimEnd('\\', '/').ToLowerInvariant()))).Replace("-", "").ToLowerInvariant();
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + CONTROL_PORT + "/api/identity");
            request.Proxy = null;
            request.Timeout = 500;
            request.ReadWriteTimeout = 500;
            using (WebResponse response = request.GetResponse())
            using (StreamReader reader = new StreamReader(response.GetResponseStream()))
                return reader.ReadToEnd().Contains("\"" + identity + "\"");
        }
        catch { return false; }
    }

    static bool IsPortOpen(int port)
    {
        try
        {
            using (TcpClient client = new TcpClient())
            {
                IAsyncResult ar = client.BeginConnect("127.0.0.1", port, null, null);
                bool success = ar.AsyncWaitHandle.WaitOne(200);
                if (!success) return false;
                client.EndConnect(ar);
                return true;
            }
        }
        catch
        {
            return false;
        }
    }

    static void GetLauncherWindowLayout(out int x, out int y, out int width, out int height)
    {
        try
        {
            var wa = Screen.PrimaryScreen.WorkingArea;
            int margin = 16;
            int gap = 16;
            x = wa.X + margin;
            y = wa.Y + margin;
            if (wa.Width >= 1800)
                width = 900;
            else if (wa.Width >= 1400)
                width = Math.Min(880, (int)((wa.Width - margin * 2 - gap) * 0.49));
            else
                width = Math.Min(wa.Width - 32, Math.Max(600, (int)((wa.Width - margin * 2 - gap) * 0.5)));

            height = Math.Min(980, Math.Max(650, wa.Height - margin * 2));
        }
        catch
        {
            x = 16;
            y = 16;
            width = 900;
            height = 960;
        }
    }

    static void LaunchBrowser(string url)
    {
        string cacheBustUrl = url + "/?v=" + DateTime.UtcNow.Ticks;
        int x, y, w, h;
        GetLauncherWindowLayout(out x, out y, out w, out h);
        string windowFlags = string.Format(" --window-position={0},{1} --window-size={2},{3} ", x, y, w, h);

        string[] browserPaths = new string[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), @"Microsoft\Edge\Application\msedge.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"Microsoft\Edge\Application\msedge.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Microsoft\Edge\Application\msedge.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"Google\Chrome\Application\chrome.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), @"Google\Chrome\Application\chrome.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Google\Chrome\Application\chrome.exe")
        };

        foreach (string bp in browserPaths)
        {
            if (File.Exists(bp))
            {
                try
                {
                    Process.Start(bp, "--app=" + cacheBustUrl + windowFlags + "--disable-features=Translate,msEdgeTranslate,TranslateUI --disable-translate --no-first-run");
                    return;
                }
                catch {}
            }
        }

        try
        {
            Process.Start(cacheBustUrl);
        }
        catch {}
    }

    static bool IsValidPython(string path)
    {
        try
        {
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) return false;

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = path;
            psi.Arguments = "-I -c \"import sys, struct; sys.exit(0 if sys.version_info >= (3, 10) and struct.calcsize('P') == 8 else 1)\"";
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;

            using (Process p = Process.Start(psi))
            {
                if (p == null) return false;
                if (!p.WaitForExit(1500))
                {
                    try { p.Kill(); } catch {}
                    return false;
                }
                return p.ExitCode == 0;
            }
        }
        catch
        {
            return false;
        }
    }

    static bool CheckForUpdates(bool showPrompt)
    {
        try
        {
            System.Net.ServicePointManager.SecurityProtocol = (System.Net.SecurityProtocolType)3072 | System.Net.SecurityProtocolType.Tls;
            using (var wc = new System.Net.WebClient())
            {
                wc.Headers.Add("User-Agent", "PC-Control-Launcher/2.0.1");

                string sumsUrl = "https://github.com/lavi-666/pc-control/releases/latest/download/SHA256SUMS.txt";
                string downloadUrl = "https://github.com/lavi-666/pc-control/releases/latest/download/Launcher.exe";

                string sumsText = wc.DownloadString(sumsUrl);
                string expectedHash = null;
                if (!string.IsNullOrEmpty(sumsText))
                {
                    if (sumsText.StartsWith("\uFEFF")) sumsText = sumsText.Substring(1);
                    string[] lines = sumsText.Split(new char[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                    foreach (string rawLine in lines)
                    {
                        string line = rawLine.Trim();
                        if (line.Length == 0 || line.StartsWith("#")) continue;
                        int firstSpace = line.IndexOfAny(new char[] { ' ', '\t' });
                        if (firstSpace > 0)
                        {
                            string hash = line.Substring(0, firstSpace).Trim().ToLowerInvariant();
                            string fpath = line.Substring(firstSpace).Trim().TrimStart('*').Trim().Replace('\\', '/');
                            string fname = Path.GetFileName(fpath);
                            if (string.Equals(fname, "Launcher.exe", StringComparison.OrdinalIgnoreCase))
                            {
                                expectedHash = hash;
                                break;
                            }
                        }
                    }
                }

                if (string.IsNullOrEmpty(expectedHash))
                {
                    if (showPrompt)
                    {
                        MessageBox.Show(
                            "Не удалось проверить обновления: в файле SHA256SUMS.txt отсутствует контрольная сумма для Launcher.exe.",
                            "PC Control — Ошибка обновления",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Warning
                        );
                    }
                    return false;
                }

                string currentExe = Assembly.GetExecutingAssembly().Location;
                string localHash = "";
                if (File.Exists(currentExe))
                {
                    using (var sha = System.Security.Cryptography.SHA256.Create())
                    {
                        byte[] bytes = File.ReadAllBytes(currentExe);
                        byte[] hash = sha.ComputeHash(bytes);
                        var sb = new System.Text.StringBuilder();
                        foreach (byte b in hash) sb.Append(b.ToString("x2"));
                        localHash = sb.ToString();
                    }
                }

                bool hasUpdate = false;
                if (!string.IsNullOrEmpty(localHash) && !string.IsNullOrEmpty(expectedHash))
                {
                    if (!string.Equals(localHash, expectedHash, StringComparison.OrdinalIgnoreCase))
                    {
                        hasUpdate = true;
                    }
                }

                if (showPrompt)
                {
                    if (hasUpdate)
                    {
                        DialogResult dr = MessageBox.Show(
                            "Доступна новая версия лаунчера PC Control!\n\n" +
                            "Загрузить и применить обновление сейчас?",
                            "PC Control — Доступно обновление",
                            MessageBoxButtons.YesNo,
                            MessageBoxIcon.Information
                        );
                        if (dr == DialogResult.Yes)
                        {
                            byte[] dlBytes = wc.DownloadData(downloadUrl);

                            // 1. Обязательная проверка контрольной суммы SHA-256
                            string dlHash = "";
                            using (var sha = System.Security.Cryptography.SHA256.Create())
                            {
                                byte[] hash = sha.ComputeHash(dlBytes);
                                var sb = new System.Text.StringBuilder();
                                foreach (byte b in hash) sb.Append(b.ToString("x2"));
                                dlHash = sb.ToString();
                            }

                            if (!string.Equals(dlHash, expectedHash, StringComparison.OrdinalIgnoreCase))
                            {
                                MessageBox.Show(
                                    "Ошибка проверки целостности обновления!\n\nКонтрольная сумма SHA-256 не совпадает.\nОбновление отменено в целях безопасности.",
                                    "PC Control — Ошибка целостности",
                                    MessageBoxButtons.OK,
                                    MessageBoxIcon.Error
                                );
                                return false;
                            }

                            // 2. Проверка размера и PE-заголовков
                            if (dlBytes.Length < 20480 || dlBytes.Length > 52428800 || dlBytes[0] != 'M' || dlBytes[1] != 'Z')
                            {
                                MessageBox.Show(
                                    "Файл обновления поврежден (некорректный размер или сигнатура MZ).",
                                    "PC Control — Ошибка обновления",
                                    MessageBoxButtons.OK,
                                    MessageBoxIcon.Error
                                );
                                return false;
                            }

                            int peOffset = BitConverter.ToInt32(dlBytes, 0x3C);
                            if (peOffset < 0 || peOffset + 4 > dlBytes.Length ||
                                dlBytes[peOffset] != 'P' || dlBytes[peOffset + 1] != 'E' || dlBytes[peOffset + 2] != 0 || dlBytes[peOffset + 3] != 0)
                            {
                                MessageBox.Show(
                                    "Файл обновления поврежден (некорректный заголовок PE).",
                                    "PC Control — Ошибка обновления",
                                    MessageBoxButtons.OK,
                                    MessageBoxIcon.Error
                                );
                                return false;
                            }

                            // 3. Сохранение файла на диск только после успешных проверок
                            string newExe = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Launcher.exe.new");
                            File.WriteAllBytes(newExe, dlBytes);

                            string updaterBat = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "scripts", "updater.bat");
                            if (File.Exists(updaterBat))
                            {
                                string baseDirNoSlash = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
                                ProcessStartInfo psi = new ProcessStartInfo("cmd.exe", "/c \"" + updaterBat + "\" \"" + baseDirNoSlash + "\" " + Process.GetCurrentProcess().Id);
                                psi.CreateNoWindow = true;
                                psi.UseShellExecute = false;
                                Process.Start(psi);
                                Environment.Exit(0);
                            }
                        }
                    }
                    else
                    {
                        MessageBox.Show(
                            "Вы используете последнюю версию программы. (2.0.1)\n\n" +
                            "Репозиторий PC Control актуален.",
                            "PC Control — Обновления",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Information
                        );
                    }
                }
                return true;
            }
        }
        catch (Exception ex)
        {
            if (showPrompt)
            {
                MessageBox.Show(
                    "Не удалось проверить обновления: сервер GitHub недоступен.\n\n" +
                    "Проверьте подключение к интернету.\n(" + ex.Message + ")",
                    "PC Control — Ошибка сети",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning
                );
            }
        }
        return false;
    }
}
