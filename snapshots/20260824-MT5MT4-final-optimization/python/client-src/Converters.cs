using System.Globalization;
using System.Windows;
using System.Windows.Data;
using System.Windows.Media;

namespace QhClient;

// 盈亏正绿负红
public sealed class PnlColorConverter : IValueConverter
{
    private static readonly Brush Up = new SolidColorBrush(Color.FromRgb(0x3F, 0xD0, 0x7F));
    private static readonly Brush Down = new SolidColorBrush(Color.FromRgb(0xF2, 0x6D, 0x6D));
    public object Convert(object value, Type t, object p, CultureInfo c)
    {
        double d = value is double v ? v : 0;
        return d >= 0 ? Up : Down;
    }
    public object ConvertBack(object v, Type t, object p, CultureInfo c) => Binding.DoNothing;
}

// bool → Visibility
public sealed class BoolToVisConverter : IValueConverter
{
    public object Convert(object value, Type t, object p, CultureInfo c)
        => (value is bool b && b) ? Visibility.Visible : Visibility.Collapsed;
    public object ConvertBack(object v, Type t, object p, CultureInfo c) => Binding.DoNothing;
}

// 连接态 → 颜色
public sealed class ConnColorConverter : IValueConverter
{
    private static readonly Brush Ok = new SolidColorBrush(Color.FromRgb(0x3F, 0xD0, 0x7F));
    private static readonly Brush Bad = new SolidColorBrush(Color.FromRgb(0xF2, 0x6D, 0x6D));
    public object Convert(object value, Type t, object p, CultureInfo c)
        => (value is bool b && b) ? Ok : Bad;
    public object ConvertBack(object v, Type t, object p, CultureInfo c) => Binding.DoNothing;
}
