// api.js - API请求工具

// 后端API基础URL
const BASE_URL = 'http://localhost:3001/api/v1';

/**
 * 封装的请求函数
 * @param {string} url - 请求路径
 * @param {Object} options - 请求选项
 * @returns {Promise<Object>} - 请求结果
 */
async function request(url, options = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${BASE_URL}${url}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'Content-Type': 'application/json',
        ...options.header
      },
      success: (response) => {
        // 处理不同的HTTP状态码
        if (response.statusCode >= 200 && response.statusCode < 300) {
          // 2xx 成功状态
          resolve(response.data);
        } else if (response.statusCode === 400) {
          // 400 错误请求
          const errorMsg = `请求参数错误: ${response.data && response.data.message ? response.data.message : '无效的请求参数'}`;
          console.error('API请求错误:', errorMsg);
          reject(new Error(errorMsg));
        } else if (response.statusCode === 401) {
          // 401 未授权
          const errorMsg = '未授权访问，请先登录';
          console.error('API请求错误:', errorMsg);
          reject(new Error(errorMsg));
        } else if (response.statusCode === 403) {
          // 403 禁止访问
          const errorMsg = '禁止访问，无权限查看该资源';
          console.error('API请求错误:', errorMsg);
          reject(new Error(errorMsg));
        } else if (response.statusCode === 404) {
          // 404 资源不存在
          const errorMsg = '请求的资源不存在';
          console.error('API请求错误:', errorMsg);
          reject(new Error(errorMsg));
        } else if (response.statusCode >= 500) {
          // 5xx 服务器错误
          const errorMsg = `服务器错误: ${response.data && response.data.message ? response.data.message : '服务器内部错误'}`;
          console.error('API请求错误:', errorMsg);
          reject(new Error(errorMsg));
        } else {
          // 其他状态码
          const errorMsg = `请求失败: ${response.statusCode} ${response.data && response.data.message ? response.data.message : '未知错误'}`;
          console.error('API请求错误:', errorMsg);
          reject(new Error(errorMsg));
        }
      },
      fail: (error) => {
        // 网络错误处理
        let errorMsg = '网络请求失败';
        
        if (error.errMsg) {
          if (error.errMsg.includes('request:fail')) {
            errorMsg = '网络请求失败，请检查网络连接';
          } else if (error.errMsg.includes('timeout')) {
            errorMsg = '网络请求超时，请稍后重试';
          } else {
            errorMsg = `网络请求失败: ${error.errMsg}`;
          }
        }
        
        console.error('API请求错误:', errorMsg);
        reject(new Error(errorMsg));
      },
      complete: () => {
        // 请求完成后的处理
      }
    });
  });
}

// 作品相关API
const worksApi = {
  /**
   * 获取作品列表
   * @param {Object} params - 请求参数
   * @returns {Promise<Object>} - 作品列表
   */
  async getWorks(params = {}) {
    return await request('/works', {
      data: params
    });
  },

  /**
   * 获取作品详情
   * @param {number} id - 作品ID
   * @param {string} openId - 用户OpenID
   * @returns {Promise<Object>} - 作品详情
   */
  async getWorkDetail(id, openId = '') {
    const params = openId ? { openId } : {};
    return await request(`/works/${id}`, {
      data: params
    });
  },

  /**
   * 获取统计数据
   * @returns {Promise<Object>} - 统计数据
   */
  async getStats() {
    return await request('/stats');
  }
};

// 分类相关API
const categoryApi = {
  /**
   * 获取分类列表
   * @returns {Promise<Object>} - 分类列表
   */
  async getCategories() {
    return await request('/categories');
  }
};

// 线索相关API
const leadApi = {
  /**
   * 创建线索
   * @param {Object} leadData - 线索数据
   * @returns {Promise<Object>} - 创建结果
   */
  async createLead(leadData) {
    return await request('/leads', {
      method: 'POST',
      data: leadData
    });
  }
};

// 联系信息API
const contactApi = {
  /**
   * 获取联系信息
   * @returns {Promise<Object>} - 联系信息
   */
  async getContactInfo() {
    return await request('/contact');
  }
};

// 关于我们API
const aboutApi = {
  /**
   * 获取关于我们信息
   * @returns {Promise<Object>} - 关于我们信息
   */
  async getAboutInfo() {
    return await request('/about');
  }
};

// 权限相关API
const permissionsApi = {
  /**
   * 根据OpenID获取用户权限
   * @param {string} openId - 用户OpenID
   * @returns {Promise<Object>} - 用户权限
   */
  async getPermissionsByOpenId(openId) {
    return await request(`/permissions/${openId}`);
  }
};

module.exports = {
  request,
  worksApi,
  contactApi,
  aboutApi,
  categoryApi,
  leadApi,
  permissionsApi
};
