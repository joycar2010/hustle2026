// app.js
App({
  globalData: {
    userInfo: null,
    userPermissions: {
      viewWorks: false,
      categories: []
    },
    isAuthenticated: false
  },
  
  onLaunch() {
    // 展示本地存储能力
    const logs = wx.getStorageSync('logs') || []
    logs.unshift(Date.now())
    wx.setStorageSync('logs', logs)

    // 初始化云函数
    try {
      wx.cloud.init({
        env: 'your-cloud-env-id', // 请替换为你的云函数环境ID
        traceUser: true
      })
      console.log('云函数初始化成功')
    } catch (error) {
      console.warn('云函数初始化失败，在本地开发环境中可能需要部署云函数', error)
    }

    // 自动登录流程
    this.autoLogin();
  },
  
  /**
   * 自动登录流程
   */
  autoLogin() {
    // 登录
    wx.login({
      success: res => {
        console.log('Login code:', res.code);
        // 发送 res.code 到后台换取 openId, sessionKey, unionId
        this.getUserOpenId(res.code);
      },
      fail: error => {
        console.error('Login failed:', error);
      }
    });
  },
  
  /**
   * 获取用户OpenID
   * @param {string} code - 登录凭证
   */
  getUserOpenId(code) {
    try {
      wx.cloud.callFunction({
        name: 'getOpenId',
        success: (openIdRes) => {
          const openId = openIdRes.result.openid;
          console.log('OpenID:', openId);
          // 存储OpenID到本地存储
          try {
            wx.setStorageSync('openId', openId);
          } catch (e) {
            console.error('存储OpenID失败:', e);
          }
          // 获取用户信息
          this.getUserInfo(openId);
        },
        fail: (error) => {
          console.error('获取OpenID失败:', error);
          // 使用默认权限
          this.setDefaultPermissions();
        }
      });
    } catch (error) {
      console.error('云函数调用失败:', error);
      // 使用默认权限
      this.setDefaultPermissions();
    }
  },
  
  /**
   * 获取用户信息
   * @param {string} openId - 用户OpenID
   */
  getUserInfo(openId) {
    // 获取微信用户信息
    wx.getUserProfile({
      desc: '用于获取您的权限信息',
      success: (userInfoRes) => {
        const userInfo = userInfoRes.userInfo;
        console.log('User Info:', userInfo);
        this.globalData.userInfo = userInfo;
        
        // 根据OpenID获取用户权限
        this.getUserPermissions(openId, userInfo);
      },
      fail: (error) => {
        console.error('获取用户信息失败:', error);
        // 使用默认权限
        this.setDefaultPermissions();
      }
    });
  },
  
  /**
   * 根据OpenID获取用户权限
   * @param {string} openId - 用户OpenID
   * @param {Object} userInfo - 用户信息
   */
  getUserPermissions(openId, userInfo) {
    const api = require('./utils/api');
    
    api.permissionsApi.getPermissionsByOpenId(openId).then(res => {
      if (res.success && res.data) {
        console.log('User Permissions:', res.data);
        this.globalData.userPermissions = res.data;
        this.globalData.isAuthenticated = true;
      } else {
        console.warn('获取权限失败，使用默认权限');
        this.setDefaultPermissions();
      }
    }).catch(() => {
      console.error('获取权限错误，使用默认权限');
      this.setDefaultPermissions();
    });
  },
  
  /**
   * 设置默认权限
   */
  setDefaultPermissions() {
    this.globalData.userPermissions = {
      viewWorks: false,
      categories: []
    };
    this.globalData.isAuthenticated = false;
    console.log('Using default permissions');
  },
  
  /**
   * 检查用户是否有权限查看作品
   * @param {Object} work - 作品信息
   * @returns {Object} - 权限检查结果
   */
  canViewWork(work) {
    const isCustomerInDatabase = this.globalData.isAuthenticated;
    const { userPermissions } = this.globalData;
    
    if (!isCustomerInDatabase) {
      // 客户不在数据库中
      // 检查作品是否公开
      if (work.isPublic === false) {
        return {
          canView: false,
          canViewDetail: false,
          reason: '该作品未开放，仅对注册客户可见'
        };
      }
      
      // 检查作品分类权限
      if (work.type && userPermissions.categories && userPermissions.categories.length > 0) {
        if (!userPermissions.categories.includes(work.type)) {
          return {
            canView: false,
            canViewDetail: false,
            reason: '您没有查看该分类作品的权限'
          };
        }
      }
      
      // 客户不在数据库中，只能查看基本信息
      return {
        canView: true,
        canViewDetail: false,
        reason: '您尚未注册为我们的客户，只能查看作品基本信息。注册后可查看完整内容。'
      };
    } else {
      // 客户已在数据库中
      // 检查作品是否公开
      if (work.isPublic === false) {
        // 作品不公开，需要检查用户权限
        // 检查用户是否有查看权限
        if (!userPermissions.viewWorks) {
          return {
            canView: false,
            canViewDetail: false,
            reason: '您没有查看作品的权限'
          };
        }
        
        // 检查分类权限
        if (work.type && userPermissions.categories && userPermissions.categories.length > 0) {
          if (!userPermissions.categories.includes(work.type)) {
            return {
              canView: false,
              canViewDetail: false,
              reason: '您没有查看该分类作品的权限'
            };
          }
        }
      }
      
      // 客户已在数据库中，且有权限
      return {
        canView: true,
        canViewDetail: true,
        reason: ''
      };
    }
  }
})