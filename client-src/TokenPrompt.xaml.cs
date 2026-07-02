using System.Windows;
using QhClient.Services;

namespace QhClient;

public partial class TokenPrompt : Window
{
    public string Token => Box.Password;
    public TokenPrompt()
    {
        InitializeComponent();
        Loaded += (_, _) => Box.Focus();
    }
    private void Ok_Click(object sender, RoutedEventArgs e) { DialogResult = true; Close(); }
    private void Cancel_Click(object sender, RoutedEventArgs e) { DialogResult = false; Close(); }

    // 统一入口: 有存的令牌直接用; 否则弹框输入并存(DPAPI)。取消返回 null。
    public static string? Ask(Window owner)
    {
        var tok = CredStore.LoadAdminToken();
        if (!string.IsNullOrEmpty(tok)) return tok;
        var dlg = new TokenPrompt { Owner = owner };
        if (dlg.ShowDialog() == true && !string.IsNullOrWhiteSpace(dlg.Token))
        {
            CredStore.SaveAdminToken(dlg.Token.Trim());
            return dlg.Token.Trim();
        }
        return null;
    }
}
