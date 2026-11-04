using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
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
    const int CONTROL_PORT = 5055;

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
            // Веб-сервер уже работает, просто открываем окно браузера с защитой от кэширования
            LaunchBrowser("http://127.0.0.1:" + CONTROL_PORT);
            return;
        }

        // 2. Ищем pythonw.exe для полностью бесшумного запуска без окна консоли
        string pythonwExe = FindPythonw(baseDir);

        if (string.IsNullOrEmpty(pythonwExe))
        {
            string winget = FindInPath("winget.exe");
            if (string.IsNullOrEmpty(winget))
            {
                string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                string candidate = Path.Combine(localApp, @"Microsoft\WindowsApps\winget.exe");
                if (File.Exists(candidate)) winget = candidate;
            }

            if (!string.IsNullOrEmpty(winget))
            {
                DialogResult res = MessageBox.Show(
                    "Интерпретатор Python не найден на вашем компьютере!\n\n" +
                    "Установить Python автоматически с помощью Windows Package Manager (winget)?\n\n" +
                    "[Да] — автоматическая установка Python 3.12\n" +
                    "[Нет] — открыть официальный сайт python.org\n" +
                    "[Отмена] — выход",
                    "PC Control — Первоначальная установка",
                    MessageBoxButtons.YesNoCancel,
                    MessageBoxIcon.Information
                );

                if (res == DialogResult.Yes)
                {
                    try
                    {
                        ProcessStartInfo winPsi = new ProcessStartInfo();
                        winPsi.FileName = winget;
                        winPsi.Arguments = "install -e --id Python.Python.3.12 --scope currentuser --accept-package-agreements --accept-source-agreements";
                        winPsi.UseShellExecute = true;
                        Process proc = Process.Start(winPsi);
                        if (proc != null)
                        {
                            proc.WaitForExit();
                            pythonwExe = FindPythonw(baseDir);
                        }
                    }
                    catch {}
                }
                else if (res == DialogResult.No)
                {
                    Process.Start("https://www.python.org/downloads/");
                    return;
                }
                else
                {
                    return;
                }
            }

            if (string.IsNullOrEmpty(pythonwExe))
            {
                DialogResult res = MessageBox.Show(
                    "Интерпретатор Python не найден на вашем компьютере!\n\n" +
                    "Для работы PC Control требуется Python (рекомендуется 3.11 или 3.12).\n" +
                    "Открыть официальный сайт для скачивания?",
                    "PC Control — Python не обнаружен",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Warning
                );
                if (res == DialogResult.Yes)
                {
                    Process.Start("https://www.python.org/downloads/");
                }
                return;
            }
        }

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = pythonwExe;
        psi.Arguments = "\"" + scriptPath + "\"";
        psi.WorkingDirectory = baseDir;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.WindowStyle = ProcessWindowStyle.Hidden;

        try
        {
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("Ошибка при запуске панели управления:\n" + ex.Message, "PC Control", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
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

    static string FindPythonw(string baseDir)
    {
        // 1. Проверяем виртуальное окружение venv
        string venvPyw = Path.Combine(baseDir, "venv", "Scripts", "pythonw.exe");
        if (IsValidPython(venvPyw)) return venvPyw;
        string venvPy = Path.Combine(baseDir, "venv", "Scripts", "python.exe");
        if (IsValidPython(venvPy)) return venvPy;

        // 2. Ищем pythonw.exe в PATH
        string fromPath = FindInPath("pythonw.exe");
        if (!string.IsNullOrEmpty(fromPath)) return fromPath;

        // 3. Проверяем стандартные пути установки Python в AppData
        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string programsPython = Path.Combine(localAppData, "Programs", "Python");
        if (Directory.Exists(programsPython))
        {
            try
            {
                string[] dirs = Directory.GetDirectories(programsPython, "Python*");
                Array.Reverse(dirs);
                foreach (string d in dirs)
                {
                    string pyw = Path.Combine(d, "pythonw.exe");
                    if (IsValidPython(pyw)) return pyw;
                    string py = Path.Combine(d, "python.exe");
                    if (IsValidPython(py)) return py;
                }
            }
            catch {}
        }

        // 4. Проверяем Microsoft Store / WindowsApps каталоги в AppData
        string winApps = Path.Combine(localAppData, @"Microsoft\WindowsApps");
        if (Directory.Exists(winApps))
        {
            try
            {
                string[] dirs = Directory.GetDirectories(winApps, "PythonSoftwareFoundation.Python*");
                Array.Reverse(dirs);
                foreach (string d in dirs)
                {
                    string pyw = Path.Combine(d, "pythonw.exe");
                    if (IsValidPython(pyw)) return pyw;
                    string py = Path.Combine(d, "python.exe");
                    if (IsValidPython(py)) return py;
                }
            }
            catch {}

            string waPyw = Path.Combine(winApps, "pythonw.exe");
            if (IsValidPython(waPyw)) return waPyw;
            string waPy = Path.Combine(winApps, "python.exe");
            if (IsValidPython(waPy)) return waPy;
            string waPy3 = Path.Combine(winApps, "python3.exe");
            if (IsValidPython(waPy3)) return waPy3;
        }

        // 5. Проверяем Program Files (x64 и x86)
        string[] programFolders = new string[]
        {
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
            @"C:\"
        };

        foreach (string folder in programFolders)
        {
            if (Directory.Exists(folder))
            {
                try
                {
                    string[] dirs = Directory.GetDirectories(folder, "Python*");
                    Array.Reverse(dirs);
                    foreach (string d in dirs)
                    {
                        string pyw = Path.Combine(d, "pythonw.exe");
                        if (IsValidPython(pyw)) return pyw;
                        string py = Path.Combine(d, "python.exe");
                        if (IsValidPython(py)) return py;
                    }
                }
                catch {}
            }
        }

        // 6. Проверяем официальный Python Launcher (pyw.exe / py.exe)
        string pywLauncher = FindInPath("pyw.exe");
        if (!string.IsNullOrEmpty(pywLauncher)) return pywLauncher;

        string winDir = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        string winPyw = Path.Combine(winDir, "pyw.exe");
        if (IsValidPython(winPyw)) return winPyw;

        string winPy = Path.Combine(winDir, "py.exe");
        if (IsValidPython(winPy)) return winPy;

        // 7. Ищем python.exe в PATH
        string fromPathPy = FindInPath("python.exe");
        if (!string.IsNullOrEmpty(fromPathPy)) return fromPathPy;

        string fromPathPy3 = FindInPath("python3.exe");
        if (!string.IsNullOrEmpty(fromPathPy3)) return fromPathPy3;

        return null;
    }

    static bool IsValidPython(string path)
    {
        try
        {
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) return false;

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = path;
            psi.Arguments = "-c \"import sys, struct; sys.exit(0 if sys.version_info >= (3, 10) and struct.calcsize('P') == 8 else 1)\"";
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

    static string FindInPath(string filename)
    {
        string pathEnv = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrEmpty(pathEnv)) return null;

        string[] paths = pathEnv.Split(';');
        foreach (string p in paths)
        {
            try
            {
                string clean = p.Trim();
                if (clean.Length > 0)
                {
                    string full = Path.Combine(clean, filename);
                    if (filename.StartsWith("py", StringComparison.OrdinalIgnoreCase)
                        ? IsValidPython(full) : File.Exists(full)) return full;
                }
            }
            catch {}
        }
        return null;
    }

    static bool CheckForUpdates(bool showPrompt)
    {
        try
        {
            System.Net.ServicePointManager.SecurityProtocol = (System.Net.SecurityProtocolType)3072 | System.Net.SecurityProtocolType.Tls;
            using (var wc = new System.Net.WebClient())
            {
                wc.Headers.Add("User-Agent", "PC-Control-Launcher/2.0.1");
                string json = wc.DownloadString("https://api.github.com/repos/lavi-666/pc-control/contents/Launcher.exe");

                string currentExe = Assembly.GetExecutingAssembly().Location;
                string localHash = "";
                if (File.Exists(currentExe))
                {
                    byte[] bytes = File.ReadAllBytes(currentExe);
                    byte[] header = System.Text.Encoding.ASCII.GetBytes("blob " + bytes.Length + "\0");
                    byte[] all = new byte[header.Length + bytes.Length];
                    Buffer.BlockCopy(header, 0, all, 0, header.Length);
                    Buffer.BlockCopy(bytes, 0, all, header.Length, bytes.Length);
                    using (var sha = System.Security.Cryptography.SHA1.Create())
                    {
                        byte[] hash = sha.ComputeHash(all);
                        var sb = new System.Text.StringBuilder();
                        foreach (byte b in hash) sb.Append(b.ToString("x2"));
                        localHash = sb.ToString();
                    }
                }

                bool hasUpdate = false;
                if (!string.IsNullOrEmpty(localHash) && !string.IsNullOrEmpty(json))
                {
                    if (!json.Contains(localHash))
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
                            string newExe = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Launcher.exe.new");
                            string downloadUrl = "https://raw.githubusercontent.com/lavi-666/pc-control/main/Launcher.exe";
                            wc.DownloadFile(downloadUrl, newExe);

                            byte[] dlBytes = File.ReadAllBytes(newExe);
                            if (dlBytes.Length > 20480 && dlBytes[0] == 'M' && dlBytes[1] == 'Z')
                            {
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
