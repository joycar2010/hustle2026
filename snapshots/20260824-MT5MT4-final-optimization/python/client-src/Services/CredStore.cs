using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace QhClient.Services;

// 本地凭证加密存储(Windows DPAPI, 仅当前用户可解)。license 绝不明文落盘。
public static class CredStore
{
    private static readonly string Path =
        System.IO.Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "QuantHedge", "cred.bin");

    public static void SaveLicense(string license)
    {
        try
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path)!);
            var enc = ProtectedData.Protect(Encoding.UTF8.GetBytes(license), null, DataProtectionScope.CurrentUser);
            File.WriteAllBytes(Path, enc);
        }
        catch { /* 存不下不阻断 */ }
    }

    public static string? LoadLicense()
    {
        try
        {
            if (!File.Exists(Path)) return null;
            var dec = ProtectedData.Unprotect(File.ReadAllBytes(Path), null, DataProtectionScope.CurrentUser);
            return Encoding.UTF8.GetString(dec);
        }
        catch { return null; }
    }

    public static void Clear()
    {
        try { if (File.Exists(Path)) File.Delete(Path); } catch { }
        try { if (File.Exists(AdminPath)) File.Delete(AdminPath); } catch { }
    }

    // ---- Admin Token(真金写操作用, 同样 DPAPI 加密) ----
    private static readonly string AdminPath =
        System.IO.Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "QuantHedge", "admin.bin");

    public static void SaveAdminToken(string tok)
    {
        try
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(AdminPath)!);
            var enc = ProtectedData.Protect(Encoding.UTF8.GetBytes(tok), null, DataProtectionScope.CurrentUser);
            File.WriteAllBytes(AdminPath, enc);
        }
        catch { }
    }
    public static string? LoadAdminToken()
    {
        try
        {
            if (!File.Exists(AdminPath)) return null;
            var dec = ProtectedData.Unprotect(File.ReadAllBytes(AdminPath), null, DataProtectionScope.CurrentUser);
            return Encoding.UTF8.GetString(dec);
        }
        catch { return null; }
    }
    public static void ClearAdminToken()
    {
        try { if (File.Exists(AdminPath)) File.Delete(AdminPath); } catch { }
    }
}
