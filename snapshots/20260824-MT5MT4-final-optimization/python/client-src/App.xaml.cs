using System.Windows;
using QhClient.Services;

namespace QhClient;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        // 统一走 WebShell: 有存密钥→注入自动登录; 无→显 web 登录页(唯一登录入口, 无原生登录框)
        var lic = CredStore.LoadLicense() ?? "";
        var shell = new WebShellWindow(lic);
        MainWindow = shell;
        shell.Show();
    }
}
