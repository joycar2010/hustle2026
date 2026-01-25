// contact.ts
const app = getApp()

Component({
  data: {
    consultTypes: ['家装设计', '公装设计', '商业空间', '其他咨询'],
    selectedType: '家装设计'
  },
  
  lifetimes: {
    attached() {
      // 页面加载时的初始化逻辑
    }
  },
  
  methods: {
    // 拨打电话
    makePhoneCall() {
      wx.makePhoneCall({
        phoneNumber: '4001234567',
        success: (res) => {
          console.log('拨打电话成功', res)
        },
        fail: (err) => {
          console.error('拨打电话失败', err)
        }
      })
    },
    
    // 提交表单
    submitForm(e) {
      const formData = e.detail.value
      console.log('表单数据:', formData)
      
      // 表单验证
      if (!formData.name || !formData.phone) {
        wx.showToast({
          title: '请填写姓名和电话',
          icon: 'none'
        })
        return
      }
      
      // 模拟提交成功
      wx.showToast({
        title: '提交成功，我们将尽快与您联系',
        icon: 'success'
      })
      
      // 重置表单
      this.setData({
        selectedType: '家装设计'
      })
    }
  }
})