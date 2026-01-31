// pages/contact/contact.js
const api = require('../../utils/api.js');

Page({
  /**
   * 页面的初始数据
   */
  data: {
    contactInfo: {
      phone: '400-123-4567',
      email: 'info@budesign.com',
      address1: '北京市朝阳区建国路88号',
      address2: '',
      workingHours: '周一至周日 9:00-21:00'
    },
    categories: [],
    selectedCategory: '',
    selectedCategoryType: '',
    isSubmitting: false
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad(options) {
    this.loadContactInfo();
    this.loadCategories();
  },

  /**
   * 加载分类数据
   */
  loadCategories() {
    api.categoryApi.getCategories()
      .then(res => {
        if (res && res.success && res.data) {
          // 对分类数据按名称升序排序
          const sortedCategories = [...res.data].sort((a, b) => {
            return a.name.localeCompare(b.name);
          });
          this.setData({
            categories: sortedCategories
          });
        }
      })
      .catch(err => {
        console.error('加载分类数据失败:', err);
      });
  },

  /**
   * 加载联系信息
   */
  loadContactInfo() {
    wx.showLoading({
      title: '加载中...'
    });

    api.aboutApi.getAboutInfo()
      .then(res => {
        wx.hideLoading();
        if (res && res.success && res.data && res.data.contactInfo) {
          const contactInfo = res.data.contactInfo;
          this.setData({
            contactInfo: contactInfo
          });
          

        }
      })
      .catch(err => {
        wx.hideLoading();
        console.error('加载联系信息失败:', err);
        wx.showToast({
          title: '加载失败，显示默认信息',
          icon: 'none',
          duration: 2000
        });
      });
  },



  /**
   * 生命周期函数--监听页面初次渲染完成
   */
  onReady() {

  },

  /**
   * 生命周期函数--监听页面显示
   */
  onShow() {
    // 每次页面显示时重新加载数据，确保获取最新版本
    this.loadContactInfo();
  },

  /**
   * 生命周期函数--监听页面隐藏
   */
  onHide() {

  },

  /**
   * 生命周期函数--监听页面卸载
   */
  onUnload() {

  },

  /**
   * 页面相关事件处理函数--监听用户下拉动作
   */
  onPullDownRefresh() {
    wx.stopPullDownRefresh();
  },

  /**
   * 页面上拉触底事件的处理函数
   */
  onReachBottom() {

  },

  /**
   * 用户点击右上角分享
   */
  onShareAppMessage() {
    return {
      title: '布珥·迈拓空间设计 - 联系我们',
      path: '/pages/contact/contact'
    };
  },



  /**
   * 拨打电话
   */
  makePhoneCall() {
    const { phone } = this.data.contactInfo;
    if (phone) {
      wx.makePhoneCall({
        phoneNumber: phone,
        success: () => {
          console.log('成功拨打电话');
        },
        fail: (err) => {
          console.error('拨打电话失败:', err);
          wx.showToast({
            title: '拨打电话失败',
            icon: 'error',
            duration: 2000
          });
        }
      });
    }
  },

  /**
   * 发送邮件
   */
  sendEmail() {
    const { email } = this.data.contactInfo;
    if (email) {
      wx.setClipboardData({
        data: email,
        success: () => {
          wx.showToast({
            title: '邮箱已复制到剪贴板',
            icon: 'success',
            duration: 2000
          });
        },
        fail: (err) => {
          console.error('复制邮箱失败:', err);
          wx.showToast({
            title: '复制邮箱失败',
            icon: 'error',
            duration: 2000
          });
        }
      });
    }
  },

  /**
   * 打开高德地图（温州）
   */
  openMap1() {
    const { map, address1 } = this.data.contactInfo;
    if (map) {
      wx.navigateTo({
        url: `/pages/webview/webview?url=${encodeURIComponent(map)}`
      });
    } else if (address1) {
      wx.openLocation({
        address: address1,
        success: () => {
          console.log('成功打开地图');
        },
        fail: (err) => {
          console.error('打开地图失败:', err);
          wx.showToast({
            title: '打开地图失败',
            icon: 'error',
            duration: 2000
          });
        }
      });
    }
  },

  /**
   * 打开高德地图（杭州）
   */
  openMap2() {
    const { map2, address2 } = this.data.contactInfo;
    if (map2) {
      wx.navigateTo({
        url: `/pages/webview/webview?url=${encodeURIComponent(map2)}`
      });
    } else if (address2) {
      wx.openLocation({
        address: address2,
        success: () => {
          console.log('成功打开地图');
        },
        fail: (err) => {
          console.error('打开地图失败:', err);
          wx.showToast({
            title: '打开地图失败',
            icon: 'error',
            duration: 2000
          });
        }
      });
    }
  },

  /**
   * 项目类型选择变化
   */
  onProjectTypeChange(e) {
    const index = e.detail.value;
    const categories = this.data.categories;
    if (categories && categories[index]) {
      this.setData({
        selectedCategory: categories[index].name,
        selectedCategoryType: categories[index].slug
      });
    }
  },

  /**
   * 提交表单
   */
  submitForm(e) {
    // 防止重复提交
    if (this.data.isSubmitting) {
      return;
    }
    
    const formData = e.detail.value;
    
    // 表单验证
    if (!formData.name || !formData.phone || !formData.message) {
      wx.showToast({
        title: '请填写必填项',
        icon: 'none'
      });
      return;
    }
    
    // 电话格式验证
    const phoneRegex = /^1[3-9]\d{9}$/;
    if (!phoneRegex.test(formData.phone)) {
      wx.showToast({
        title: '请输入正确的手机号码',
        icon: 'none'
      });
      return;
    }
    
    // 设置提交状态为true，防止重复提交
    this.setData({
      isSubmitting: true
    });
    
    // 提交线索数据到后台
    wx.showLoading({
      title: '提交中...'
    });
    
    // 获取微信用户信息
    this.getUserInfo().then(userInfo => {
      // 构建线索数据
      const leadData = {
        name: formData.name,
        phone: formData.phone,
        email: formData.email || '',
        projectType: this.data.selectedCategoryType || 'other',
        budget: formData.budget || '',
        status: 'new',
        description: formData.message,
        wechatAvatar: userInfo.avatarUrl || '',
        wechatOpenId: userInfo.openId || '',
        wechatNickname: userInfo.nickName || ''
      };
      
      return api.leadApi.createLead(leadData);
    }).then(res => {
      wx.hideLoading();
      // 重置提交状态
      this.setData({
        isSubmitting: false
      });
      
      if (res && res.success) {
        wx.showToast({
          title: '提交成功，我们会尽快联系您',
          icon: 'success'
        });
        
        // 重置表单
        this.setData({
          selectedCategory: '',
          selectedCategoryType: ''
        });
        
        // 重置表单输入 - 微信小程序中不需要手动reset，表单会自动清空
      } else {
        wx.showToast({
          title: '提交失败，请重试',
          icon: 'none'
        });
      }
    })
    .catch(err => {
      wx.hideLoading();
      // 重置提交状态
      this.setData({
        isSubmitting: false
      });
      
      console.error('提交表单失败:', err);
      
      // 检查是否是重复提交错误
      if (err.message && err.message.includes('您已经提交过咨询')) {
        wx.showModal({
          title: '提示',
          content: '您已经提交过咨询，我们会尽快联系您！',
          showCancel: false,
          confirmText: '确定'
        });
      } else {
        wx.showToast({
          title: '提交失败，请重试',
          icon: 'none'
        });
      }
    });
  },

  /**
   * 获取微信用户信息
   */
  getUserInfo() {
    return new Promise((resolve, reject) => {
      // 先尝试使用wx.getUserProfile获取用户信息
      wx.getUserProfile({
        desc: '用于完善客户信息',
        success: (res) => {
          const userInfo = res.userInfo;
          
          // 尝试获取openId
          try {
            wx.cloud.callFunction({
              name: 'getOpenId',
              success: (openIdRes) => {
                resolve({
                  ...userInfo,
                  openId: openIdRes.result.openid
                });
              },
              fail: () => {
                // 如果获取openId失败，仍然返回用户信息
                resolve(userInfo);
              }
            });
          } catch (error) {
            // 云函数调用失败，仍然返回用户信息
            console.warn('云函数调用失败:', error);
            resolve(userInfo);
          }
        },
        fail: () => {
          // 如果用户拒绝授权，仍然允许提交表单
          resolve({});
        }
      });
    });
  },


});
