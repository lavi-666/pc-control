using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("PC Control Setup")]
[assembly: AssemblyProduct("PC Control")]
[assembly: AssemblyDescription("PC Control Setup and Desktop Installation Wizard")]
[assembly: AssemblyCompany("PC Control")]
[assembly: AssemblyVersion("2.4.0.0")]
[assembly: AssemblyFileVersion("2.4.0.0")]

namespace PCControl.Installer
{
    public class InstallerOptions
    {
        public bool Silent = false;
        public bool NoRun = false;
        public bool DryRun = false;
        public string TargetDir = null;
        public string SandboxDir = null;
        public bool CreateDesktopShortcut = true;
        public bool CreateStartMenuShortcut = true;
        public bool CreateStartupShortcut = false;
        public string ReportFile = null;
    }

    public static class ShellHelper
    {
        public static void CreateShortcut(string shortcutPath, string targetExe, string workingDir, string iconPath, string description)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return;
                dynamic shell = Activator.CreateInstance(shellType);
                dynamic shortcut = shell.CreateShortcut(shortcutPath);
                shortcut.TargetPath = targetExe;
                shortcut.WorkingDirectory = workingDir;
                if (!string.IsNullOrEmpty(iconPath) && File.Exists(iconPath))
                {
                    shortcut.IconLocation = iconPath + ",0";
                }
                shortcut.Description = description;
                shortcut.Save();
            }
            catch { }
        }

        public static void RegisterUninstall(string installDir, string version, bool isSandbox, string sandboxDir)
        {
            if (isSandbox)
            {
                // В песочнице регистрируем в мок-файле песочницы
                string mockFile = Path.Combine(sandboxDir, "mock_windows_state.json");
                try
                {
                    string json = File.Exists(mockFile) ? File.ReadAllText(mockFile, Encoding.UTF8) : "{}";
                    string entry = string.Format("\"installed_app\": {{\"name\": \"PC Control\", \"version\": \"{0}\", \"dir\": \"{1}\"}}", version, installDir.Replace("\\", "\\\\"));
                    File.WriteAllText(Path.Combine(sandboxDir, "mock_uninstall_reg.json"), "{" + entry + "}", new UTF8Encoding(false));
                }
                catch { }
                return;
            }

            try
            {
                string subkey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\PC Control";
                using (RegistryKey k = Registry.CurrentUser.CreateSubKey(subkey))
                {
                    if (k != null)
                    {
                        k.SetValue("DisplayName", "PC Control", RegistryValueKind.String);
                        k.SetValue("DisplayVersion", version, RegistryValueKind.String);
                        k.SetValue("Publisher", "PC Control", RegistryValueKind.String);
                        k.SetValue("InstallLocation", installDir, RegistryValueKind.String);
                        string ico = Path.Combine(installDir, "pc_control.ico");
                        if (File.Exists(ico)) k.SetValue("DisplayIcon", ico, RegistryValueKind.String);
                        string uninst = File.Exists(Path.Combine(installDir, "unstaller.exe")) 
                            ? Path.Combine(installDir, "unstaller.exe") 
                            : Path.Combine(installDir, "Uninstall.exe");
                        k.SetValue("UninstallString", "\"" + uninst + "\"", RegistryValueKind.String);
                        k.SetValue("QuietUninstallString", "\"" + uninst + "\" --silent", RegistryValueKind.String);
                        k.SetValue("URLInfoAbout", "https://github.com/lavi-666/pc-control", RegistryValueKind.String);
                        k.SetValue("NoModify", 1, RegistryValueKind.DWord);
                        k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                    }
                }
            }
            catch { }
        }
    }

    public static class SetupEngine
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
                    Console.SetOut(new StreamWriter(stdOut, new UTF8Encoding(false)) { AutoFlush = true });
            }
            catch { }
        }

        public static bool ValidateInstallDirectory(string rawPath, out string validationError, out string normalizedPath)
        {
            validationError = null;
            normalizedPath = null;

            if (string.IsNullOrWhiteSpace(rawPath))
            {
                validationError = "Путь к папке установки не может быть пустым.";
                return false;
            }

            try
            {
                normalizedPath = Path.GetFullPath(rawPath.Trim().Trim('"', '\''));
            }
            catch (Exception ex)
            {
                validationError = "Недопустимый формат пути: " + ex.Message;
                return false;
            }

            // Запрет установки непосредственно в корень любого диска (C:\, D:\, etc.)
            string root = Path.GetPathRoot(normalizedPath);
            if (!string.IsNullOrEmpty(root))
            {
                string normTrim = normalizedPath.TrimEnd('\\', '/');
                string rootTrim = root.TrimEnd('\\', '/');
                if (string.Equals(normTrim, rootTrim, StringComparison.OrdinalIgnoreCase) ||
                    Regex.IsMatch(normalizedPath, @"^[a-zA-Z]:\\?$"))
                {
                    validationError = "Установка непосредственно в корень диска (" + root + ") запрещена в целях безопасности системы. Выберите отдельную подпапку (например, " + Path.Combine(root, "PC Control") + ").";
                    return false;
                }
            }

            // Запрет установки в системные каталоги Windows
            string winDir = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            if (!string.IsNullOrEmpty(winDir) && normalizedPath.StartsWith(winDir, StringComparison.OrdinalIgnoreCase))
            {
                validationError = "Установка в системную директорию Windows (" + winDir + ") строго запрещена.";
                return false;
            }

            string sysDir = Environment.GetFolderPath(Environment.SpecialFolder.System);
            if (!string.IsNullOrEmpty(sysDir) && normalizedPath.StartsWith(sysDir, StringComparison.OrdinalIgnoreCase))
            {
                validationError = "Установка в системную директорию System32 строго запрещена.";
                return false;
            }

            // Защита от установки прямо в корни системных папок пользователя
            var genericFolders = new Environment.SpecialFolder[]
            {
                Environment.SpecialFolder.ProgramFiles,
                Environment.SpecialFolder.ProgramFilesX86,
                Environment.SpecialFolder.UserProfile,
                Environment.SpecialFolder.Desktop,
                Environment.SpecialFolder.DesktopDirectory,
                Environment.SpecialFolder.MyDocuments,
                Environment.SpecialFolder.ApplicationData,
                Environment.SpecialFolder.LocalApplicationData
            };

            foreach (var sf in genericFolders)
            {
                try
                {
                    string specPath = Environment.GetFolderPath(sf);
                    if (!string.IsNullOrEmpty(specPath) && string.Equals(normalizedPath.TrimEnd('\\', '/'), specPath.TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase))
                    {
                        normalizedPath = Path.Combine(specPath, "PC Control");
                        break;
                    }
                }
                catch { }
            }

            // Проверка на посторонние файлы в уже существующей директории
            if (Directory.Exists(normalizedPath))
            {
                try
                {
                    var existingFiles = Directory.GetFiles(normalizedPath);
                    if (existingFiles.Length > 0)
                    {
                        bool isPcControl = File.Exists(Path.Combine(normalizedPath, "install_manifest.json")) ||
                                           File.Exists(Path.Combine(normalizedPath, "Launcher.exe")) ||
                                           File.Exists(Path.Combine(normalizedPath, "pc_control.ico"));
                        if (!isPcControl)
                        {
                            // Директория содержит посторонние файлы — изолируем в подпапку PC Control
                            normalizedPath = Path.Combine(normalizedPath, "PC Control");
                        }
                    }
                }
                catch { }
            }

            return true;
        }

        public class ManifestFileInfo
        {
            public string RelPath;
            public long Size;
            public string Sha256;
        }

        public static string ComputeFileSha256(string filePath)
        {
            using (var sha = SHA256.Create())
            using (var fs = File.OpenRead(filePath))
            {
                byte[] hash = sha.ComputeHash(fs);
                var sb = new StringBuilder(hash.Length * 2);
                foreach (byte b in hash) sb.Append(b.ToString("x2"));
                return sb.ToString();
            }
        }

        public static string GetDefaultInstallDir()
        {
            string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (string.IsNullOrEmpty(localApp)) localApp = @"C:\PCControl";
            return Path.Combine(localApp, @"Programs\PC Control");
        }

        public static Stream GetPayloadStream()
        {
            var asm = Assembly.GetExecutingAssembly();
            foreach (string name in asm.GetManifestResourceNames())
            {
                if (name.EndsWith("payload.zip", StringComparison.OrdinalIgnoreCase) ||
                    name.IndexOf("payload", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return asm.GetManifestResourceStream(name);
                }
            }

            // Fallback для разработки: проверяем рядом лежащие архивы
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string[] candidates = new string[]
            {
                Path.Combine(baseDir, "payload.zip"),
                Path.Combine(baseDir, "dist", "PC_Control_Windows.zip"),
                Path.Combine(baseDir, "PC_Control_Windows.zip")
            };
            foreach (string c in candidates)
            {
                if (File.Exists(c)) return new FileStream(c, FileMode.Open, FileAccess.Read, FileShare.Read);
            }
            return null;
        }

        public static bool ExtractPayload(Stream zipStream, string targetDir, Action<string, int> progressCallback, out string error)
        {
            error = null;
            if (zipStream == null)
            {
                error = "Встроенный архив приложения не найден.";
                return false;
            }

            try
            {
                Directory.CreateDirectory(targetDir);
                var installedFiles = new List<ManifestFileInfo>();

                using (var archive = new ZipArchive(zipStream, ZipArchiveMode.Read))
                {
                    int total = archive.Entries.Count;
                    int count = 0;

                    foreach (var entry in archive.Entries)
                    {
                        count++;
                        int pct = Math.Min(90, (int)((count * 100.0) / Math.Max(1, total)));

                        // Убираем префикс корневой папки, если архив упакован как PC_Control/...
                        string relName = entry.FullName;
                        if (relName.StartsWith("PC_Control/", StringComparison.OrdinalIgnoreCase))
                            relName = relName.Substring("PC_Control/".Length);
                        else if (relName.StartsWith("PC_Control\\", StringComparison.OrdinalIgnoreCase))
                            relName = relName.Substring("PC_Control\\".Length);

                        if (string.IsNullOrWhiteSpace(relName)) continue;

                        string destPath = Path.Combine(targetDir, relName.Replace('/', '\\'));

                        if (entry.FullName.EndsWith("/") || entry.FullName.EndsWith("\\"))
                        {
                            Directory.CreateDirectory(destPath);
                            continue;
                        }

                        Directory.CreateDirectory(Path.GetDirectoryName(destPath));
                        progressCallback("Распаковка: " + relName, pct);

                        // Извлечение и вычисление SHA-256 в один потоковый проход
                        long fileLen = 0;
                        string shaHex;
                        using (var entryStream = entry.Open())
                        using (var outFs = new FileStream(destPath, FileMode.Create, FileAccess.Write, FileShare.None))
                        using (var sha = SHA256.Create())
                        {
                            byte[] buffer = new byte[64 * 1024];
                            int read;
                            while ((read = entryStream.Read(buffer, 0, buffer.Length)) > 0)
                            {
                                outFs.Write(buffer, 0, read);
                                sha.TransformBlock(buffer, 0, read, null, 0);
                                fileLen += read;
                            }
                            sha.TransformFinalBlock(new byte[0], 0, 0);
                            byte[] hashBytes = sha.Hash;
                            var sbHash = new StringBuilder(hashBytes.Length * 2);
                            foreach (byte b in hashBytes) sbHash.Append(b.ToString("x2"));
                            shaHex = sbHash.ToString();
                        }

                        installedFiles.Add(new ManifestFileInfo
                        {
                            RelPath = relName.Replace('/', '\\'),
                            Size = fileLen,
                            Sha256 = shaHex
                        });
                    }
                }

                // Запись манифеста установки install_manifest.json
                progressCallback("Формирование манифеста целостности установки...", 92);
                string manifestPath = Path.Combine(targetDir, "install_manifest.json");
                var sb = new StringBuilder();
                sb.AppendLine("{");
                sb.AppendLine("  \"schema_version\": 1,");
                sb.AppendLine("  \"application\": \"PC Control\",");
                sb.AppendLine("  \"version\": \"2.4.0\",");
                sb.AppendLine(string.Format("  \"installed_at\": \"{0:o}\",", DateTime.UtcNow));
                sb.AppendLine(string.Format("  \"install_dir\": \"{0}\",", targetDir.Replace("\\", "\\\\")));
                sb.AppendLine("  \"files\": [");
                for (int i = 0; i < installedFiles.Count; i++)
                {
                    var f = installedFiles[i];
                    sb.Append(string.Format("    {{\"path\": \"{0}\", \"size\": {1}, \"sha256\": \"{2}\"}}",
                        f.RelPath.Replace("\\", "\\\\"), f.Size, f.Sha256));
                    if (i < installedFiles.Count - 1) sb.Append(",");
                    sb.AppendLine();
                }
                sb.AppendLine("  ]");
                sb.AppendLine("}");
                File.WriteAllText(manifestPath, sb.ToString(), new UTF8Encoding(false));

                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }
    }

    public class SetupWizardForm : Form
    {
        private InstallerOptions _opts;
        private TextBox _txtTargetDir;
        private Button _btnBrowse;
        private CheckBox _chkDesktop;
        private CheckBox _chkStartMenu;
        private CheckBox _chkStartup;
        private CheckBox _chkLaunchNow;
        private ProgressBar _progressBar;
        private Label _lblStatus;
        private Button _btnInstall;
        private Button _btnCancel;
        private Panel _pnlStep1;
        private Panel _pnlStep2;

        public SetupWizardForm(InstallerOptions opts)
        {
            _opts = opts;
            InitializeComponents();
        }

        private void InitializeComponents()
        {
            Text = "Установка PC Control";
            Size = new Size(650, 480);
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            BackColor = Color.FromArgb(15, 23, 42); // slate-900
            ForeColor = Color.FromArgb(248, 250, 252); // slate-50
            Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            // Header Banner
            var pnlHeader = new Panel
            {
                Dock = DockStyle.Top,
                Height = 72,
                BackColor = Color.FromArgb(30, 41, 59) // slate-800
            };
            var lblTitle = new Label
            {
                Text = "PC Control — Мастер установки",
                Font = new Font("Segoe UI", 13.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(56, 189, 248), // sky-400
                Location = new Point(24, 14),
                AutoSize = true
            };
            var lblSubtitle = new Label
            {
                Text = "Установка центра удалённого управления компьютером для Windows и Android",
                Font = new Font("Segoe UI", 9f),
                ForeColor = Color.FromArgb(148, 163, 184), // slate-400
                Location = new Point(25, 42),
                AutoSize = true
            };
            pnlHeader.Controls.Add(lblTitle);
            pnlHeader.Controls.Add(lblSubtitle);
            Controls.Add(pnlHeader);

            // Container Panel 1: Settings
            _pnlStep1 = new Panel
            {
                Location = new Point(24, 88),
                Size = new Size(585, 290)
            };

            var lblDir = new Label
            {
                Text = "Папка установки (рекомендуется для текущего пользователя без прав админа):",
                Location = new Point(0, 8),
                AutoSize = true
            };
            _pnlStep1.Controls.Add(lblDir);

            _txtTargetDir = new TextBox
            {
                Location = new Point(0, 34),
                Size = new Size(475, 26),
                BackColor = Color.FromArgb(30, 41, 59),
                ForeColor = Color.White,
                Font = new Font("Segoe UI", 9f),
                Text = _opts.TargetDir ?? SetupEngine.GetDefaultInstallDir()
            };
            _pnlStep1.Controls.Add(_txtTargetDir);

            _btnBrowse = new Button
            {
                Text = "Обзор...",
                Location = new Point(485, 33),
                Size = new Size(95, 28),
                BackColor = Color.FromArgb(51, 65, 85),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _btnBrowse.FlatAppearance.BorderSize = 0;
            _btnBrowse.Click += (s, e) => {
                using (var fbd = new FolderBrowserDialog())
                {
                    fbd.Description = "Выберите папку для установки PC Control:";
                    if (fbd.ShowDialog() == DialogResult.OK) _txtTargetDir.Text = fbd.SelectedPath;
                }
            };
            _pnlStep1.Controls.Add(_btnBrowse);

            var lblOptions = new Label
            {
                Text = "Дополнительные параметры:",
                Location = new Point(0, 85),
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                AutoSize = true
            };
            _pnlStep1.Controls.Add(lblOptions);

            _chkDesktop = new CheckBox
            {
                Text = "Создать ярлык на Рабочем столе",
                Checked = true,
                Location = new Point(5, 115),
                AutoSize = true
            };
            _pnlStep1.Controls.Add(_chkDesktop);

            _chkStartMenu = new CheckBox
            {
                Text = "Создать ярлык в меню «Пуск»",
                Checked = true,
                Location = new Point(5, 145),
                AutoSize = true
            };
            _pnlStep1.Controls.Add(_chkStartMenu);

            _chkStartup = new CheckBox
            {
                Text = "Запускать PC Control автоматически при входе в систему",
                Checked = false,
                Location = new Point(5, 175),
                AutoSize = true
            };
            _pnlStep1.Controls.Add(_chkStartup);

            _chkLaunchNow = new CheckBox
            {
                Text = "Запустить PC Control после завершения установки",
                Checked = true,
                Location = new Point(5, 215),
                AutoSize = true,
                ForeColor = Color.FromArgb(56, 189, 248)
            };
            _pnlStep1.Controls.Add(_chkLaunchNow);

            Controls.Add(_pnlStep1);

            // Container Panel 2: Progress
            _pnlStep2 = new Panel
            {
                Location = new Point(24, 88),
                Size = new Size(585, 290),
                Visible = false
            };

            var lblProgressTitle = new Label
            {
                Text = "Выполняется установка файлов приложения...",
                Location = new Point(0, 30),
                Font = new Font("Segoe UI", 11f, FontStyle.Bold),
                ForeColor = Color.FromArgb(56, 189, 248),
                AutoSize = true
            };
            _pnlStep2.Controls.Add(lblProgressTitle);

            _progressBar = new ProgressBar
            {
                Location = new Point(0, 80),
                Size = new Size(580, 24),
                Style = ProgressBarStyle.Continuous,
                Value = 0
            };
            _pnlStep2.Controls.Add(_progressBar);

            _lblStatus = new Label
            {
                Text = "Подготовка...",
                Location = new Point(0, 115),
                Size = new Size(580, 45),
                ForeColor = Color.FromArgb(203, 213, 225)
            };
            _pnlStep2.Controls.Add(_lblStatus);
            Controls.Add(_pnlStep2);

            // Bottom Buttons
            int btnY = 392;
            _btnInstall = new Button
            {
                Text = "Установить",
                Size = new Size(130, 36),
                Location = new Point(365, btnY),
                BackColor = Color.FromArgb(2, 132, 199), // sky-600
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 10f, FontStyle.Bold)
            };
            _btnInstall.FlatAppearance.BorderSize = 0;
            _btnInstall.Click += (s, e) => StartInstallation();
            Controls.Add(_btnInstall);

            _btnCancel = new Button
            {
                Text = "Отмена",
                Size = new Size(100, 36),
                Location = new Point(505, btnY),
                BackColor = Color.FromArgb(51, 65, 85),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _btnCancel.FlatAppearance.BorderSize = 0;
            _btnCancel.Click += (s, e) => Close();
            Controls.Add(_btnCancel);
        }

        private void StartInstallation()
        {
            string target = _txtTargetDir.Text.Trim();
            if (string.IsNullOrEmpty(target))
            {
                MessageBox.Show("Укажите папку для установки.", "PC Control Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            string valErr;
            string normPath;
            if (!SetupEngine.ValidateInstallDirectory(target, out valErr, out normPath))
            {
                MessageBox.Show(valErr, "PC Control Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            _opts.TargetDir = normPath;
            _txtTargetDir.Text = normPath;
            _opts.CreateDesktopShortcut = _chkDesktop.Checked;
            _opts.CreateStartMenuShortcut = _chkStartMenu.Checked;
            _opts.CreateStartupShortcut = _chkStartup.Checked;
            _opts.NoRun = !_chkLaunchNow.Checked;

            _pnlStep1.Visible = false;
            _pnlStep2.Visible = true;
            _btnInstall.Enabled = false;
            _btnCancel.Enabled = false;

            var t = new Thread(() => {
                string error;
                bool ok = RunInstallSequence(_opts, (msg, pct) => {
                    if (InvokeRequired)
                    {
                        Invoke(new Action(() => {
                            _lblStatus.Text = msg;
                            _progressBar.Value = Math.Min(100, Math.Max(0, pct));
                        }));
                    }
                }, out error);

                if (InvokeRequired)
                {
                    Invoke(new Action(() => {
                        if (ok)
                        {
                            _lblStatus.Text = "Установка успешно завершена!";
                            _progressBar.Value = 100;
                            _btnCancel.Text = "Готово";
                            _btnCancel.Enabled = true;
                            _btnCancel.BackColor = Color.FromArgb(16, 185, 129); // emerald-500
                            _btnCancel.Click -= (s, e) => Close();
                            _btnCancel.Click += (s, e) => {
                                if (!_opts.NoRun)
                                {
                                    string launcher = Path.Combine(_opts.TargetDir, "Launcher.exe");
                                    if (File.Exists(launcher)) Process.Start(launcher);
                                }
                                Close();
                            };
                        }
                        else
                        {
                            MessageBox.Show("Ошибка во время установки:\n" + error, "PC Control Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
                            _btnCancel.Enabled = true;
                        }
                    }));
                }
            });
            t.IsBackground = true;
            t.Start();
        }

        public static bool RunInstallSequence(InstallerOptions opts, Action<string, int> progress, out string error)
        {
            error = null;
            string target = Path.GetFullPath(opts.TargetDir);
            progress("Чтение установочного пакета...", 5);

            Stream payload = SetupEngine.GetPayloadStream();
            if (payload == null)
            {
                error = "Не удалось обнаружить установочный архив программы.";
                return false;
            }

            using (payload)
            {
                if (!SetupEngine.ExtractPayload(payload, target, progress, out error))
                {
                    return false;
                }
            }

            progress("Создание ярлыков...", 90);
            string launcherExe = Path.Combine(target, "Launcher.exe");
            string iconPath = Path.Combine(target, "pc_control.ico");

            if (opts.CreateDesktopShortcut)
            {
                string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                string lnk = Path.Combine(desktop, "PC Control.lnk");
                ShellHelper.CreateShortcut(lnk, launcherExe, target, iconPath, "PC Control Center");
            }

            if (opts.CreateStartMenuShortcut)
            {
                string programs = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                string startDir = Path.Combine(programs, "PC Control");
                Directory.CreateDirectory(startDir);
                string lnk = Path.Combine(startDir, "PC Control.lnk");
                ShellHelper.CreateShortcut(lnk, launcherExe, target, iconPath, "PC Control Center");

                string uninstLnk = Path.Combine(startDir, "Удалить PC Control.lnk");
                string uninstExe = File.Exists(Path.Combine(target, "unstaller.exe")) 
                    ? Path.Combine(target, "unstaller.exe") 
                    : Path.Combine(target, "Uninstall.exe");
                ShellHelper.CreateShortcut(uninstLnk, uninstExe, target, iconPath, "Удаление PC Control");
            }

            if (opts.CreateStartupShortcut)
            {
                string startup = Environment.GetFolderPath(Environment.SpecialFolder.Startup);
                string lnk = Path.Combine(startup, "PC_Control_Server.lnk");
                ShellHelper.CreateShortcut(lnk, launcherExe, target, iconPath, "PC Control Server Auto-start");
            }

            progress("Регистрация программы в Windows...", 98);
            ShellHelper.RegisterUninstall(target, "2.4.0", !string.IsNullOrEmpty(opts.SandboxDir), opts.SandboxDir);

            progress("Установка завершена.", 100);
            return true;
        }
    }

    public static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            var opts = new InstallerOptions();

            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                string al = a.ToLowerInvariant();
                if (al == "/silent" || al == "/verysilent" || al == "--silent" || al == "-s")
                {
                    opts.Silent = true;
                }
                else if (al == "/norun" || al == "--no-run")
                {
                    opts.NoRun = true;
                }
                else if (al == "--dry-run")
                {
                    opts.DryRun = true;
                }
                else if ((al == "/dir" || al == "--dir") && i + 1 < args.Length)
                {
                    opts.TargetDir = args[++i].Trim('"');
                }
                else if (al.StartsWith("/dir="))
                {
                    opts.TargetDir = a.Substring(5).Trim('"');
                }
                else if (al == "--sandbox-dir" && i + 1 < args.Length)
                {
                    opts.SandboxDir = args[++i].Trim('"');
                }
                else if (al == "--report-file" && i + 1 < args.Length)
                {
                    opts.ReportFile = args[++i].Trim('"');
                }
                else if (al == "/?" || al == "--help" || al == "-h")
                {
                    SetupEngine.EnsureConsoleOutput();
                    Console.WriteLine("PC Control Setup");
                    Console.WriteLine("Usage: PC-Control-Setup.exe [/SILENT] [/DIR=\"path\"] [/NORUN]");
                    return 0;
                }
            }

            if (string.IsNullOrEmpty(opts.TargetDir))
            {
                opts.TargetDir = !string.IsNullOrEmpty(opts.SandboxDir)
                    ? Path.Combine(opts.SandboxDir, "installed_app")
                    : SetupEngine.GetDefaultInstallDir();
            }

            string valErr;
            string normPath;
            if (!SetupEngine.ValidateInstallDirectory(opts.TargetDir, out valErr, out normPath))
            {
                if (opts.Silent)
                {
                    SetupEngine.EnsureConsoleOutput();
                    Console.WriteLine("ERROR: " + valErr);
                    return 1;
                }
            }
            else
            {
                opts.TargetDir = normPath;
            }

            if (!opts.Silent)
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new SetupWizardForm(opts));
                return 0;
            }

            SetupEngine.EnsureConsoleOutput();
            Console.WriteLine("Starting PC Control silent installation...");
            Console.WriteLine("Target directory: " + opts.TargetDir);

            string error;
            bool ok = SetupWizardForm.RunInstallSequence(opts, (msg, pct) => {
                Console.WriteLine(string.Format("[{0}%] {1}", pct, msg));
            }, out error);

            if (!ok)
            {
                Console.WriteLine("ERROR: " + error);
                return 1;
            }

            Console.WriteLine("Installation successfully completed.");
            if (!opts.NoRun && string.IsNullOrEmpty(opts.SandboxDir))
            {
                string launcher = Path.Combine(opts.TargetDir, "Launcher.exe");
                if (File.Exists(launcher)) Process.Start(launcher);
            }
            return 0;
        }
    }
}
