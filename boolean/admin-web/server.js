const express = require('express');
const session = require('express-session');
const bodyParser = require('body-parser');
const path = require('path');
const fs = require('fs');
const fileUpload = require('express-fileupload');

// 创建上传目录
const uploadDir = path.join(__dirname, 'public', 'uploads');
if (!fs.existsSync(uploadDir)) {
  fs.mkdirSync(uploadDir, { recursive: true });
}

// 导入lowdb数据库
const { db, initDatabase, getNextId } = require('./db');
const bcrypt = require('bcrypt');
const saltRounds = 10;

// 创建数据目录
const dataDir = path.join(__dirname, 'data');
if (!fs.existsSync(dataDir)) {
  fs.mkdirSync(dataDir);
}

const app = express();
const PORT = process.env.PORT || 3001;

// 中间件配置
app.use(bodyParser.urlencoded({ extended: true, limit: '10mb' }));
app.use(bodyParser.json({ limit: '10mb' }));
app.use(fileUpload({ useTempFiles: true, tempFileDir: '/tmp/' }));

// 先定义中间件，再定义API路由，最后定义静态文件路由

// 跨域配置
app.use((req, res, next) => {
  // 允许携带凭证时不能使用通配符
  const origin = req.headers.origin || '*';
  res.setHeader('Access-Control-Allow-Origin', origin);
  // 允许的请求方法
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  // 允许的请求头
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  // 允许携带凭证
  res.setHeader('Access-Control-Allow-Credentials', true);
  
  // 处理OPTIONS请求
  if (req.method === 'OPTIONS') {
    res.sendStatus(200);
    return;
  }
  
  next();
});

// 图片上传API
app.post('/api/v1/upload', (req, res) => {
  try {
    if (!req.files || !req.files.image) {
      return res.json({
        success: false,
        message: '请选择要上传的图片'
      });
    }
    
    const image = req.files.image;
    const fileName = `${Date.now()}-${Math.round(Math.random() * 1E9)}.${image.name.split('.').pop()}`;
    const filePath = path.join(uploadDir, fileName);
    
    // 保存图片
    image.mv(filePath, (err) => {
      if (err) {
        console.error('保存图片失败:', err);
        return res.json({
          success: false,
          message: '保存图片失败'
        });
      }
      
      // 返回图片URL
      const imageUrl = `/uploads/${fileName}`;
      res.json({
        success: true,
        data: {
          url: imageUrl,
          fileName: fileName
        }
      });
    });
  } catch (error) {
    console.error('上传图片错误:', error);
    res.json({
      success: false,
      message: '上传图片失败'
    });
  }
});

// Session配置
app.use(session({
  secret: 'space-design-secret-key',
  resave: true,
  saveUninitialized: false,
  rolling: true,
  cookie: {
    maxAge: 24 * 60 * 60 * 1000, // 24小时
    httpOnly: true,
    secure: false,
    sameSite: 'lax'
  }
}));

// 生产环境移除会话调试中间件
// app.use((req, res, next) => {
//   // 记录会话ID和用户信息
//   console.log('Session Debug:', {
//     url: req.url,
//     sessionId: req.sessionID,
//     hasUser: !!req.session.user,
//     user: req.session.user ? req.session.user.username : 'anonymous',
//     sessionLength: req.session.cookie.maxAge
//   });
//   next();
// });

// 访问控制中间件
function requireAuth(req, res, next) {
  if (req.session.user) {
    next();
  } else {
    res.status(401).json({ success: false, message: '未授权访问' });
  }
}

// 基于权限的访问控制中间件
function requirePermission(permission) {
  return (req, res, next) => {
    if (req.session.user) {
      const user = db.data.users.find(u => u.username === req.session.user.username);
      if (user) {
        // 检查用户是否有对应权限
        if (user.permissions && user.permissions[permission]) {
            next();
        } else {
            res.status(403).json({ success: false, message: '无权限访问' });
        }
      } else {
        res.status(404).json({ success: false, message: '用户不存在' });
      }
    } else {
      res.status(401).json({ success: false, message: '未登录' });
    }
  };
}

// 页面访问权限控制中间件
function requirePageAccess(page) {
  return (req, res, next) => {
    if (req.session.user) {
      const user = db.data.users.find(u => u.username === req.session.user.username);
      if (user) {
        // 检查用户是否有对应权限
        if (user.permissions && user.permissions[page] === true) {
            next();
        } else {
            // 对于页面访问，重定向到无权限页面或仪表盘
            res.redirect('/dashboard');
        }
      } else {
        res.redirect('/login');
      }
    } else {
      res.redirect('/login');
    }
  };
}

// 根路径路由 - 重定向到登录页面
app.get('/', (req, res) => {
  if (req.session.user) {
    res.redirect('/dashboard');
  } else {
    res.redirect('/login');
  }
});

// 操作员管理页面路由
app.get('/users', requirePageAccess('users'), (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'users.html'));
});

// 登录页面路由
app.get('/login', (req, res) => {
  if (req.session.user) {
    res.redirect('/dashboard');
  } else {
    res.sendFile(path.join(__dirname, 'public', 'login.html'));
  }
});



// 仪表盘路由
app.get('/dashboard', requirePageAccess('dashboard'), (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'dashboard.html'));
});

// 作品管理页面路由
app.get('/works', requirePageAccess('works'), (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'works.html'));
});

// 分类管理页面路由
app.get('/categories', requirePageAccess('categories'), (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'categories.html'));
});

// 线索管理页面路由
app.get('/leads', requirePageAccess('leads'), (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'leads.html'));
});

// 数据统计页面路由
app.get('/stats', requirePageAccess('stats'), (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'stats.html'));
});

// 系统设置页面路由
app.get('/settings', requirePageAccess('settings'), (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'settings.html'));
});

// 关于我们页面路由 - 重定向到品牌管理
app.get('/about', requirePageAccess('brand'), (req, res) => {
  res.redirect('/brand-edit');
});

// 客户管理页面路由
app.get('/customers', requirePageAccess('customers'), (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'customers.html'));
});

// 品牌管理页面路由
app.get('/brand-edit', requirePageAccess('brand'), (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'brand-edit.html'));
});

// 获取统计数据的API端点
app.get('/api/v1/stats', requirePermission('stats'), (req, res) => {
  try {
    // 从数据库获取统计数据
    const worksCount = db.data.works.length;
    const categoriesCount = db.data.categories.length;
    const leadsCount = db.data.leads.length;
    const views = db.data.works.reduce((total, work) => total + (work.views || 0), 0);
    
    const stats = {
      works: worksCount,
      categories: categoriesCount,
      leads: leadsCount,
      views
    };
    
    res.json({
      success: true,
      data: stats,
      message: '统计数据获取成功'
    });
  } catch (error) {
    console.error('获取统计数据失败:', error);
    res.status(500).json({
      success: false,
      message: '获取统计数据失败'
    });
  }
});

// 获取详细统计数据的API端点
app.get('/api/v1/stats/detailed', requirePermission('stats'), (req, res) => {
  try {
    // 从数据库获取数据
    const categories = db.data.categories;
    const works = db.data.works;
    const leads = db.data.leads;
    
    // 计算作品按分类分布
    const worksByCategory = {};
    categories.forEach(category => {
      worksByCategory[category.name] = works.filter(work => work.type === category.slug).length;
    });
    
    // 计算线索按状态分布
    const leadsByStatus = {
      'new': leads.filter(lead => lead.status === 'new').length,
      'processing': leads.filter(lead => lead.status === 'processing').length,
      'completed': leads.filter(lead => lead.status === 'completed').length,
      'canceled': leads.filter(lead => lead.status === 'canceled').length
    };
    
    // 计算详细统计数据
    const detailedStats = categories.map(category => {
      const categoryWorks = works.filter(work => work.type === category.slug);
      const worksCount = categoryWorks.length;
      const views = categoryWorks.reduce((total, work) => total + (work.views || 0), 0);
      const leadsCount = leads.filter(lead => lead.projectType === category.slug).length;
      const conversionRate = worksCount > 0 ? ((leadsCount / worksCount) * 100).toFixed(2) : 0;
      
      return {
        category: category.name,
        worksCount,
        views,
        leadsCount,
        conversionRate
      };
    });
    
    // 计算总数和变化量
    const totalWorks = works.length;
    const totalCategories = categories.length;
    const totalLeads = leads.length;
    const totalViews = works.reduce((total, work) => total + (work.views || 0), 0);
    
    // 模拟本月变化量（实际项目中应该从数据库查询）
    const worksChange = Math.floor(Math.random() * 10) + 1;
    const categoriesChange = Math.floor(Math.random() * 3) + 0;
    const leadsChange = Math.floor(Math.random() * 8) + 2;
    const viewsChange = (Math.random() * 20 + 5).toFixed(1);
    
    // 返回详细统计数据
    const detailedStatsData = {
      totalWorks,
      totalCategories,
      totalLeads,
      totalViews,
      worksChange,
      categoriesChange,
      leadsChange,
      viewsChange: parseFloat(viewsChange),
      worksByCategory,
      leadsByStatus,
      detailedStats
    };
    
    res.json({
      success: true,
      data: detailedStatsData,
      message: '详细统计数据获取成功'
    });
  } catch (error) {
    console.error('获取详细统计数据失败:', error);
    res.status(500).json({
      success: false,
      message: '获取详细统计数据失败'
    });
  }
});

// 登出路由
app.get('/logout', (req, res) => {
  req.session.destroy();
  res.redirect('/login');
});

// 作品管理API端点

// 获取作品列表
app.get('/api/v1/works', (req, res) => {
  try {
    // 获取查询参数
    const { type, featured } = req.query;
    
    // 从数据库获取作品
    let works = [...db.data.works];
    
    // 如果指定了分类，进行筛选
    if (type) {
      works = works.filter(work => work.type === type);
    }
    
    // 如果指定了精选状态，进行筛选
    if (featured !== undefined) {
      const isFeatured = featured === 'true';
      works = works.filter(work => work.isFeatured === isFeatured);
    }
    
    // 排序逻辑：先按精选状态排序（精选作品在前），再按更新时间倒序排序
    works = works.sort((a, b) => {
      // 先比较精选状态
      if (a.isFeatured && !b.isFeatured) return -1;
      if (!a.isFeatured && b.isFeatured) return 1;
      // 如果精选状态相同，按更新时间倒序排序
      return new Date(b.updatedAt) - new Date(a.updatedAt);
    });
    
    res.json({
      success: true,
      data: works,
      total: works.length,
      message: '获取作品列表成功'
    });
  } catch (error) {
    console.error('获取作品列表失败:', error);
    res.status(500).json({
      success: false,
      message: '获取作品列表失败'
    });
  }
});

// 更新作品权限状态
app.put('/api/v1/works/:id/permission', requirePermission('works'), async (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const { isPublic } = req.body;
    
    const workIndex = db.data.works.findIndex(w => w.id === id);
    if (workIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '作品不存在'
      });
    }
    
    // 更新权限状态
    db.data.works[workIndex] = {
      ...db.data.works[workIndex],
      isPublic: Boolean(isPublic),
      updatedAt: new Date().toISOString()
    };
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: db.data.works[workIndex],
      message: '更新作品权限状态成功'
    });
  } catch (error) {
    console.error('更新作品权限状态失败:', error);
    res.status(500).json({
      success: false,
      message: '更新作品权限状态失败'
    });
  }
});

// 更新作品精选状态
app.put('/api/v1/works/:id/feature', requirePermission('works'), async (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const { isFeatured } = req.body;
    
    const workIndex = db.data.works.findIndex(w => w.id === id);
    if (workIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '作品不存在'
      });
    }
    
    // 更新精选状态
    db.data.works[workIndex] = {
      ...db.data.works[workIndex],
      isFeatured: Boolean(isFeatured),
      updatedAt: new Date().toISOString()
    };
    
    // 记录操作日志
    const operationLog = {
      id: Date.now(),
      action: 'update_work_featured',
      userId: req.session.user ? req.session.user.id : null,
      username: req.session.user ? req.session.user.username : 'system',
      workId: id,
      workTitle: db.data.works[workIndex].title,
      oldValue: !isFeatured,
      newValue: isFeatured,
      timestamp: new Date().toISOString(),
      ip: req.ip,
      userAgent: req.headers['user-agent']
    };
    
    // 添加到操作日志数组
    if (!db.data.operationLogs) {
      db.data.operationLogs = [];
    }
    db.data.operationLogs.push(operationLog);
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: db.data.works[workIndex],
      message: '更新作品精选状态成功'
    });
  } catch (error) {
    console.error('更新作品精选状态失败:', error);
    res.status(500).json({
      success: false,
      message: '更新作品精选状态失败'
    });
  }
});

// 获取单个作品详情
app.get('/api/v1/works/:id', (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const work = db.data.works.find(w => w.id === id);
    
    if (work) {
      // 获取OpenID参数（从查询参数中获取）
      const openId = req.query.openId;
      
      // 服务端权限验证，对于未设置isPublic字段的作品，默认视为不公开
      if (work.isPublic !== true) {
        // 作品不公开，需要验证用户权限
        if (!openId) {
          // 没有提供OpenID，拒绝访问
          return res.status(403).json({
            success: false,
            message: '需要登录才能访问该作品'
          });
        }
        
        // 查找具有该OpenID的客户
        const customer = db.data.customers.find(c => c.wechatOpenId === openId);
        
        if (!customer || !customer.permissions || !customer.permissions.viewWorks) {
          // 客户不存在或没有查看权限
          return res.status(403).json({
            success: false,
            message: '您没有查看该作品的权限'
          });
        }
        
        // 检查作品分类权限
        if (work.type && customer.permissions.categories && customer.permissions.categories.length > 0) {
          if (!customer.permissions.categories.includes(work.type)) {
            // 客户没有查看该分类作品的权限
            return res.status(403).json({
              success: false,
              message: '您没有查看该分类作品的权限'
            });
          }
        }
      }
      
      res.json({
        success: true,
        data: work,
        message: '获取作品详情成功'
      });
    } else {
      res.status(404).json({
        success: false,
        message: '作品不存在'
      });
    }
  } catch (error) {
    console.error('获取作品详情失败:', error);
    res.status(500).json({
      success: false,
      message: '获取作品详情失败'
    });
  }
});

// 添加作品
app.post('/api/v1/works', requirePermission('works'), async (req, res) => {
  try {
    const { title, type, area, location, coverImage, images, description, isPublic, designPeriod, style, designDescription, designConcept, functionPlanning, materialSelection, highlights, spaceType } = req.body;
    
    // 验证必填字段
    if (!title || !type || !area || !location || !coverImage || !images) {
      return res.status(400).json({
        success: false,
        message: '标题、类型、面积、城市、封面图片和图片列表为必填字段'
      });
    }
    
    // 验证字段类型
    if (typeof title !== 'string' || title.trim().length === 0) {
      return res.status(400).json({
        success: false,
        message: '标题必须是有效的字符串'
      });
    }
    
    if (typeof type !== 'string') {
      return res.status(400).json({
        success: false,
        message: '类型必须是有效的字符串'
      });
    }
    
    if (typeof area !== 'number' || area <= 0) {
      return res.status(400).json({
        success: false,
        message: '面积必须是有效的正数'
      });
    }
    
    if (typeof location !== 'string' || location.trim().length === 0) {
      return res.status(400).json({
        success: false,
        message: '城市必须是有效的字符串'
      });
    }
    
    if (typeof coverImage !== 'string' || coverImage.trim().length === 0) {
      return res.status(400).json({
        success: false,
        message: '封面图片必须是有效的URL'
      });
    }
    
    if (!Array.isArray(images) || images.length === 0) {
      return res.status(400).json({
        success: false,
        message: '图片列表必须是非空数组'
      });
    }
    
    // 验证图片列表中的每个URL
    for (const image of images) {
      if (typeof image !== 'string' || image.trim().length === 0) {
        return res.status(400).json({
          success: false,
          message: '图片列表中的每个元素必须是有效的URL'
        });
      }
    }
    
    // 验证分类是否存在
    const category = db.data.categories.find(c => c.slug === type);
    if (!category) {
      return res.status(400).json({
        success: false,
        message: '指定的分类不存在'
      });
    }
    
    // 创建新作品
    const newWork = {
      id: getNextId('work'),
      title: title.trim(),
      type,
      area,
      location: location.trim(),
      coverImage: coverImage.trim(),
      images: images.map(img => img.trim()),
      description: description ? description.trim() : '',
      designPeriod: designPeriod ? designPeriod.trim() : '6个月',
      style: style ? style.trim() : '现代简约',
      designDescription: designDescription ? designDescription.trim() : '设计描述内容，包括设计概念、空间规划、功能布局等详细信息。',
      designConcept: designConcept ? designConcept.trim() : '设计理念内容，包括设计思路、创意来源、设计目标等详细信息。',
      functionPlanning: functionPlanning ? functionPlanning.trim() : '功能规划内容，包括空间功能分区、流线规划、使用需求分析等详细信息。',
      materialSelection: materialSelection ? materialSelection.trim() : '材料选择内容，包括主要材料、色彩搭配、质感对比等详细信息。',
      highlights: highlights || [
        '开放式流动空间，视野更加开阔',
        '主次分明布局，功能分区合理',
        '自然光线引入，创造舒适氛围',
        '材质纹理对比，提升空间质感',
        '大面玻璃幕墙，充分采光通风'
      ],
      spaceType: spaceType ? spaceType.trim() : '住宅',
      views: 0,
      isPublic: isPublic !== undefined ? Boolean(isPublic) : false,
      isFeatured: isFeatured !== undefined ? Boolean(isFeatured) : false,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // 添加到数据库
    db.data.works.push(newWork);
    
    // 更新分类的作品数量
    category.worksCount++;
    category.updatedAt = new Date().toISOString();
    
    // 保存数据库
    db.write();
    
    res.status(201).json({
      success: true,
      data: newWork,
      message: '添加作品成功'
    });
  } catch (error) {
    console.error('添加作品失败:', error);
    res.status(500).json({
      success: false,
      message: '添加作品失败'
    });
  }
});

// 编辑作品
app.put('/api/v1/works/:id', requirePermission('works'), async (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const workIndex = db.data.works.findIndex(w => w.id === id);
    
    if (workIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '作品不存在'
      });
    }
    
    const { title, type, area, location, coverImage, images, description, isPublic, designPeriod, style, designDescription, designConcept, functionPlanning, materialSelection, highlights, spaceType } = req.body;
    
    // 验证必填字段
    if (!title || !type || !area || !location || !coverImage || !images) {
      return res.status(400).json({
        success: false,
        message: '标题、类型、面积、城市、封面图片和图片列表为必填字段'
      });
    }
    
    // 验证字段类型
    if (typeof title !== 'string' || title.trim().length === 0) {
      return res.status(400).json({
        success: false,
        message: '标题必须是有效的字符串'
      });
    }
    
    if (typeof type !== 'string') {
      return res.status(400).json({
        success: false,
        message: '类型必须是有效的字符串'
      });
    }
    
    if (typeof area !== 'number' || area <= 0) {
      return res.status(400).json({
        success: false,
        message: '面积必须是有效的正数'
      });
    }
    
    if (typeof location !== 'string' || location.trim().length === 0) {
      return res.status(400).json({
        success: false,
        message: '城市必须是有效的字符串'
      });
    }
    
    if (typeof coverImage !== 'string' || coverImage.trim().length === 0) {
      return res.status(400).json({
        success: false,
        message: '封面图片必须是有效的URL'
      });
    }
    
    if (!Array.isArray(images) || images.length === 0) {
      return res.status(400).json({
        success: false,
        message: '图片列表必须是非空数组'
      });
    }
    
    // 验证图片列表中的每个URL
    for (const image of images) {
      if (typeof image !== 'string' || image.trim().length === 0) {
        return res.status(400).json({
          success: false,
          message: '图片列表中的每个元素必须是有效的URL'
        });
      }
    }
    
    // 验证分类是否存在
    const category = db.data.categories.find(c => c.slug === type);
    if (!category) {
      return res.status(400).json({
        success: false,
        message: '指定的分类不存在'
      });
    }
    
    // 获取原作品类型，用于更新分类作品数量
    const originalWork = db.data.works[workIndex];
    const originalType = originalWork.type;
    
    // 更新作品
    const updatedWork = {
      ...originalWork,
      title: title.trim(),
      type,
      area,
      location: location.trim(),
      coverImage: coverImage.trim(),
      images: images.map(img => img.trim()),
      description: description ? description.trim() : '',
      designPeriod: designPeriod ? designPeriod.trim() : originalWork.designPeriod || '6个月',
      style: style ? style.trim() : originalWork.style || '现代简约',
      designDescription: designDescription ? designDescription.trim() : originalWork.designDescription || '设计描述内容，包括设计概念、空间规划、功能布局等详细信息。',
      designConcept: designConcept ? designConcept.trim() : originalWork.designConcept || '设计理念内容，包括设计思路、创意来源、设计目标等详细信息。',
      functionPlanning: functionPlanning ? functionPlanning.trim() : originalWork.functionPlanning || '功能规划内容，包括空间功能分区、流线规划、使用需求分析等详细信息。',
      materialSelection: materialSelection ? materialSelection.trim() : originalWork.materialSelection || '材料选择内容，包括主要材料、色彩搭配、质感对比等详细信息。',
      highlights: highlights || originalWork.highlights || [
        '开放式流动空间，视野更加开阔',
        '主次分明布局，功能分区合理',
        '自然光线引入，创造舒适氛围',
        '材质纹理对比，提升空间质感',
        '大面玻璃幕墙，充分采光通风'
      ],
      spaceType: spaceType ? spaceType.trim() : originalWork.spaceType || '住宅',
      isPublic: isPublic !== undefined ? Boolean(isPublic) : originalWork.isPublic,
      isFeatured: isFeatured !== undefined ? Boolean(isFeatured) : originalWork.isFeatured,
      updatedAt: new Date().toISOString()
    };
    
    db.data.works[workIndex] = updatedWork;
    
    // 如果类型发生变化，更新分类作品数量
    if (originalType !== type) {
      // 减少原分类的作品数量
      const originalCategory = db.data.categories.find(c => c.slug === originalType);
      if (originalCategory && originalCategory.worksCount > 0) {
        originalCategory.worksCount--;
        originalCategory.updatedAt = new Date().toISOString();
      }
      
      // 增加新分类的作品数量
      category.worksCount++;
      category.updatedAt = new Date().toISOString();
    }
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: updatedWork,
      message: '编辑作品成功'
    });
  } catch (error) {
    console.error('编辑作品失败:', error);
    res.status(500).json({
      success: false,
      message: '编辑作品失败'
    });
  }
});

// 删除作品
app.delete('/api/v1/works/:id', requirePermission('works'), async (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const workIndex = db.data.works.findIndex(w => w.id === id);
    
    if (workIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '作品不存在'
      });
    }
    
    // 获取作品类型，用于更新分类作品数量
    const work = db.data.works[workIndex];
    const workType = work.type;
    
    // 删除作品
    db.data.works.splice(workIndex, 1);
    
    // 更新分类的作品数量
    const category = db.data.categories.find(c => c.slug === workType);
    if (category && category.worksCount > 0) {
      category.worksCount--;
      category.updatedAt = new Date().toISOString();
    }
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      message: '删除作品成功'
    });
  } catch (error) {
    console.error('删除作品失败:', error);
    res.status(500).json({
      success: false,
      message: '删除作品失败'
    });
  }
});

// 分类管理API端点

// 获取分类列表
app.get('/api/v1/categories', (req, res) => {
  try {
    // 从数据库获取所有分类并按创建时间倒序排序
    const categories = [...db.data.categories].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    res.json({
      success: true,
      data: categories,
      message: '获取分类列表成功'
    });
  } catch (error) {
    console.error('获取分类列表失败:', error);
    res.status(500).json({
      success: false,
      message: '获取分类列表失败'
    });
  }
});

// 获取单个分类详情
app.get('/api/v1/categories/:id', requirePermission('categories'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const category = db.data.categories.find(c => c.id === id);
    
    if (category) {
      res.json({
        success: true,
        data: category,
        message: '获取分类详情成功'
      });
    } else {
      res.status(404).json({
        success: false,
        message: '分类不存在'
      });
    }
  } catch (error) {
    console.error('获取分类详情失败:', error);
    res.status(500).json({
      success: false,
      message: '获取分类详情失败'
    });
  }
});

// 添加分类
app.post('/api/v1/categories', requirePermission('categories'), (req, res) => {
  try {
    const { name, slug, description } = req.body;
    
    // 验证必填字段
    if (!name || !slug) {
      return res.status(400).json({
        success: false,
        message: '分类名称和分类标识为必填字段'
      });
    }
    
    // 验证分类标识是否已存在
    const existingCategory = db.data.categories.find(c => c.slug === slug);
    if (existingCategory) {
      return res.status(400).json({
        success: false,
        message: '分类标识已存在'
      });
    }
    
    // 创建新分类
    const newCategory = {
      id: getNextId('category'),
      name,
      slug,
      description: description || '',
      worksCount: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // 添加到数据库
    db.data.categories.push(newCategory);
    
    // 保存数据库
    db.write();
    
    res.status(201).json({
      success: true,
      data: newCategory,
      message: '添加分类成功'
    });
  } catch (error) {
    console.error('添加分类失败:', error);
    res.status(500).json({
      success: false,
      message: '添加分类失败'
    });
  }
});

// 编辑分类
app.put('/api/v1/categories/:id', requirePermission('categories'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const categoryIndex = db.data.categories.findIndex(c => c.id === id);
    
    if (categoryIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '分类不存在'
      });
    }
    
    const { name, slug, description } = req.body;
    
    // 验证必填字段
    if (!name || !slug) {
      return res.status(400).json({
        success: false,
        message: '分类名称和分类标识为必填字段'
      });
    }
    
    // 验证分类标识是否已存在（排除当前分类）
    const existingCategory = db.data.categories.find(c => c.slug === slug && c.id !== id);
    if (existingCategory) {
      return res.status(400).json({
        success: false,
        message: '分类标识已存在'
      });
    }
    
    // 更新分类
    db.data.categories[categoryIndex] = {
      ...db.data.categories[categoryIndex],
      name,
      slug,
      description: description || '',
      updatedAt: new Date().toISOString()
    };
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: db.data.categories[categoryIndex],
      message: '编辑分类成功'
    });
  } catch (error) {
    console.error('编辑分类失败:', error);
    res.status(500).json({
      success: false,
      message: '编辑分类失败'
    });
  }
});

// 删除分类
app.delete('/api/v1/categories/:id', requirePermission('categories'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const categoryIndex = db.data.categories.findIndex(c => c.id === id);
    
    if (categoryIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '分类不存在'
      });
    }
    
    const category = db.data.categories[categoryIndex];
    
    // 检查分类下是否有作品
    if (category.worksCount > 0) {
      return res.status(400).json({
        success: false,
        message: '该分类下存在作品，无法删除'
      });
    }
    
    // 删除分类
    db.data.categories.splice(categoryIndex, 1);
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      message: '删除分类成功'
    });
  } catch (error) {
    console.error('删除分类失败:', error);
    res.status(500).json({
      success: false,
      message: '删除分类失败'
    });
  }
});

// 客户管理API端点

// 获取客户列表
app.get('/api/v1/customers', requirePermission('customers'), (req, res) => {
  try {
    // 从数据库获取所有客户并按创建时间倒序排序
    let customers = [...db.data.customers].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    
    // 如果指定了客户类型，进行筛选
    const { type } = req.query;
    if (type) {
      customers = customers.filter(customer => customer.customerType === type);
    }
    
    res.json({
      success: true,
      data: customers,
      message: '获取客户列表成功'
    });
  } catch (error) {
    console.error('获取客户列表失败:', error);
    res.status(500).json({
      success: false,
      message: '获取客户列表失败'
    });
  }
});

// 获取单个客户详情
app.get('/api/v1/customers/:id', requirePermission('customers'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const customer = db.data.customers.find(c => c.id === id);
    
    if (customer) {
      res.json({
        success: true,
        data: customer,
        message: '获取客户详情成功'
      });
    } else {
      res.status(404).json({
        success: false,
        message: '客户不存在'
      });
    }
  } catch (error) {
    console.error('获取客户详情失败:', error);
    res.status(500).json({
      success: false,
      message: '获取客户详情失败'
    });
  }
});

// 添加客户
app.post('/api/v1/customers', requirePermission('customers'), (req, res) => {
  try {
    const { wechatAvatar, wechatNickname, name, phone, email, customerType, permissions } = req.body;
    
    // 验证必填字段
    if (!name || !phone || !customerType) {
      return res.status(400).json({
        success: false,
        message: '客户名称、联系电话和客户类型为必填字段'
      });
    }
    
    // 检查是否已经存在相同电话或邮箱的客户
    const existingCustomer = db.data.customers.find(customer => 
      customer.phone === phone || (email && customer.email === email)
    );
    
    if (existingCustomer) {
      return res.status(400).json({
        success: false,
        message: '该客户已存在'
      });
    }
    
    // 创建新客户
    const newCustomer = {
      id: getNextId('customer'),
      wechatAvatar: wechatAvatar || '',
      wechatNickname: wechatNickname || '',
      name,
      phone,
      email: email || '',
      customerType,
      permissions: permissions || {
        viewWorks: true,
        categories: []
      },
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // 添加到数据库
    db.data.customers.push(newCustomer);
    
    // 保存数据库
    db.write();
    
    res.status(201).json({
      success: true,
      data: newCustomer,
      message: '添加客户成功'
    });
  } catch (error) {
    console.error('添加客户失败:', error);
    res.status(500).json({
      success: false,
      message: '添加客户失败'
    });
  }
});

// 编辑客户
app.put('/api/v1/customers/:id', requirePermission('customers'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const customerIndex = db.data.customers.findIndex(c => c.id === id);
    
    if (customerIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '客户不存在'
      });
    }
    
    const { wechatAvatar, wechatNickname, name, phone, email, customerType, permissions } = req.body;
    
    // 验证必填字段
    if (!name || !phone || !customerType) {
      return res.status(400).json({
        success: false,
        message: '客户名称、联系电话和客户类型为必填字段'
      });
    }
    
    // 检查是否已经存在相同电话或邮箱的客户（排除当前客户）
    const existingCustomer = db.data.customers.find(customer => 
      (customer.phone === phone || (email && customer.email === email)) && customer.id !== id
    );
    
    if (existingCustomer) {
      return res.status(400).json({
        success: false,
        message: '该客户已存在'
      });
    }
    
    // 更新客户
    const updatedCustomer = {
      ...db.data.customers[customerIndex],
      wechatAvatar: wechatAvatar || '',
      wechatNickname: wechatNickname || '',
      name,
      phone,
      email: email || '',
      customerType,
      permissions: permissions || {
        viewWorks: true,
        categories: []
      },
      updatedAt: new Date().toISOString()
    };
    
    db.data.customers[customerIndex] = updatedCustomer;
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: updatedCustomer,
      message: '编辑客户成功'
    });
  } catch (error) {
    console.error('编辑客户失败:', error);
    res.status(500).json({
      success: false,
      message: '编辑客户失败'
    });
  }
});

// 删除客户
app.delete('/api/v1/customers/:id', requirePermission('customers'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const customerIndex = db.data.customers.findIndex(c => c.id === id);
    
    if (customerIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '客户不存在'
      });
    }
    
    // 删除客户
    db.data.customers.splice(customerIndex, 1);
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      message: '删除客户成功'
    });
  } catch (error) {
    console.error('删除客户失败:', error);
    res.status(500).json({
      success: false,
      message: '删除客户失败'
    });
  }
});

// 客户分类API端点

// 获取客户分类列表
app.get('/api/v1/customer-categories', requirePermission('customers'), (req, res) => {
  try {
    // 从数据库获取所有客户分类并按创建时间倒序排序
    const categories = [...db.data.customerCategories].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    res.json({
      success: true,
      data: categories,
      message: '获取客户分类列表成功'
    });
  } catch (error) {
    console.error('获取客户分类列表失败:', error);
    res.status(500).json({
      success: false,
      message: '获取客户分类列表失败'
    });
  }
});

// 添加客户分类
app.post('/api/v1/customer-categories', requirePermission('customers'), (req, res) => {
  try {
    const { name, description } = req.body;
    
    // 验证必填字段
    if (!name) {
      return res.status(400).json({
        success: false,
        message: '分类名称为必填字段'
      });
    }
    
    // 检查分类名称是否已存在
    const existingCategory = db.data.customerCategories.find(c => c.name === name);
    if (existingCategory) {
      return res.status(400).json({
        success: false,
        message: '分类名称已存在'
      });
    }
    
    // 创建新客户分类
    const newCategory = {
      id: getNextId('customerCategory'),
      name,
      description: description || '',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // 添加到数据库
    db.data.customerCategories.push(newCategory);
    
    // 保存数据库
    db.write();
    
    res.status(201).json({
      success: true,
      data: newCategory,
      message: '添加客户分类成功'
    });
  } catch (error) {
    console.error('添加客户分类失败:', error);
    res.status(500).json({
      success: false,
      message: '添加客户分类失败'
    });
  }
});

// 编辑客户分类
app.put('/api/v1/customer-categories/:id', requirePermission('customers'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const categoryIndex = db.data.customerCategories.findIndex(c => c.id === id);
    
    if (categoryIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '客户分类不存在'
      });
    }
    
    const { name, description } = req.body;
    
    // 验证必填字段
    if (!name) {
      return res.status(400).json({
        success: false,
        message: '分类名称为必填字段'
      });
    }
    
    // 检查分类名称是否已存在（排除当前分类）
    const existingCategory = db.data.customerCategories.find(c => c.name === name && c.id !== id);
    if (existingCategory) {
      return res.status(400).json({
        success: false,
        message: '分类名称已存在'
      });
    }
    
    // 更新客户分类
    const updatedCategory = {
      ...db.data.customerCategories[categoryIndex],
      name,
      description: description || '',
      updatedAt: new Date().toISOString()
    };
    
    db.data.customerCategories[categoryIndex] = updatedCategory;
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: updatedCategory,
      message: '编辑客户分类成功'
    });
  } catch (error) {
    console.error('编辑客户分类失败:', error);
    res.status(500).json({
      success: false,
      message: '编辑客户分类失败'
    });
  }
});

// 删除客户分类
app.delete('/api/v1/customer-categories/:id', requirePermission('customers'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const categoryIndex = db.data.customerCategories.findIndex(c => c.id === id);
    
    if (categoryIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '客户分类不存在'
      });
    }
    
    const categoryName = db.data.customerCategories[categoryIndex].name;
    
    // 检查是否有客户使用该分类
    const customerUsingCategory = db.data.customers.find(customer => customer.customerType === categoryName);
    if (customerUsingCategory) {
      return res.status(400).json({
        success: false,
        message: '该分类下存在客户，无法删除'
      });
    }
    
    // 删除客户分类
    db.data.customerCategories.splice(categoryIndex, 1);
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      message: '删除客户分类成功'
    });
  } catch (error) {
    console.error('删除客户分类失败:', error);
    res.status(500).json({
      success: false,
      message: '删除客户分类失败'
    });
  }
});

// 线索管理API端点

// 获取线索列表
app.get('/api/v1/leads', requirePermission('leads'), (req, res) => {
  try {
    // 从数据库获取所有线索并按创建时间倒序排序
    const leads = [...db.data.leads].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    res.json({
      success: true,
      data: leads,
      message: '获取线索列表成功'
    });
  } catch (error) {
    console.error('获取线索列表失败:', error);
    res.status(500).json({
      success: false,
      message: '获取线索列表失败'
    });
  }
});

// 获取单个线索详情
app.get('/api/v1/leads/:id', requirePermission('leads'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const lead = db.data.leads.find(l => l.id === id);
    
    if (lead) {
      res.json({
        success: true,
        data: lead,
        message: '获取线索详情成功'
      });
    } else {
      res.status(404).json({
        success: false,
        message: '线索不存在'
      });
    }
  } catch (error) {
    console.error('获取线索详情失败:', error);
    res.status(500).json({
      success: false,
      message: '获取线索详情失败'
    });
  }
});

// 添加线索
app.post('/api/v1/leads', (req, res) => {
  try {
    const { name, phone, email, projectType, budget, status, description, wechatAvatar, wechatOpenId, wechatNickname } = req.body;
    
    // 验证必填字段
    if (!name || !phone || !projectType || !status) {
      return res.status(400).json({
        success: false,
        message: '客户名称、联系电话、项目类型和状态为必填字段'
      });
    }
    
    // 检查是否已经存在相同电话或邮箱的线索
    const existingLead = db.data.leads.find(lead => 
      lead.phone === phone || (email && lead.email === email)
    );
    
    if (existingLead) {
      return res.status(400).json({
        success: false,
        message: '您已经提交过咨询，我们会尽快联系您'
      });
    }
    
    // 创建新线索
    const newLead = {
      id: getNextId('lead'),
      name,
      phone,
      email: email || '',
      projectType,
      budget: budget || '',
      status,
      description: description || '',
      wechatAvatar: wechatAvatar || '',
      wechatOpenId: wechatOpenId || '',
      wechatNickname: wechatNickname || '',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // 添加到数据库
    db.data.leads.push(newLead);
    
    // 保存数据库
    db.write();
    
    res.status(201).json({
      success: true,
      data: newLead,
      message: '添加线索成功'
    });
  } catch (error) {
    console.error('添加线索失败:', error);
    res.status(500).json({
      success: false,
      message: '添加线索失败'
    });
  }
});

// 编辑线索
app.put('/api/v1/leads/:id', requirePermission('leads'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const leadIndex = db.data.leads.findIndex(l => l.id === id);
    
    if (leadIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '线索不存在'
      });
    }
    
    const { name, phone, email, projectType, budget, status, description, wechatAvatar, wechatOpenId, wechatNickname } = req.body;
    
    // 验证必填字段
    if (!name || !phone || !projectType || !status) {
      return res.status(400).json({
        success: false,
        message: '客户名称、联系电话、项目类型和状态为必填字段'
      });
    }
    
    // 更新线索
    db.data.leads[leadIndex] = {
      ...db.data.leads[leadIndex],
      name,
      phone,
      email: email || '',
      projectType,
      budget: budget || '',
      status,
      description: description || '',
      wechatAvatar: wechatAvatar || '',
      wechatOpenId: wechatOpenId || '',
      wechatNickname: wechatNickname || '',
      updatedAt: new Date().toISOString()
    };
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: db.data.leads[leadIndex],
      message: '编辑线索成功'
    });
  } catch (error) {
    console.error('编辑线索失败:', error);
    res.status(500).json({
      success: false,
      message: '编辑线索失败'
    });
  }
});

// 删除线索
app.delete('/api/v1/leads/:id', requirePermission('leads'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const leadIndex = db.data.leads.findIndex(l => l.id === id);
    
    if (leadIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '线索不存在'
      });
    }
    
    // 删除线索
    db.data.leads.splice(leadIndex, 1);
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      message: '删除线索成功'
    });
  } catch (error) {
    console.error('删除线索失败:', error);
    res.status(500).json({
      success: false,
      message: '删除线索失败'
    });
  }
});

// 更新线索状态
app.put('/api/v1/leads/:id/status', requirePermission('leads'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const { status } = req.body;
    
    // 验证状态值
    const validStatuses = ['new', 'processing', 'completed', 'canceled'];
    if (!validStatuses.includes(status)) {
      return res.status(400).json({
        success: false,
        message: '无效的状态值，有效的状态值为：new, processing, completed, canceled'
      });
    }
    
    const leadIndex = db.data.leads.findIndex(l => l.id === id);
    if (leadIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '线索不存在'
      });
    }
    
    // 获取原状态
    const originalStatus = db.data.leads[leadIndex].status;
    
    // 更新状态
    db.data.leads[leadIndex] = {
      ...db.data.leads[leadIndex],
      status,
      updatedAt: new Date().toISOString()
    };
    
    // 记录操作日志
    const operationLog = {
      id: Date.now(),
      action: 'update_lead_status',
      userId: req.session.user ? req.session.user.id : null,
      username: req.session.user ? req.session.user.username : 'system',
      leadId: id,
      leadName: db.data.leads[leadIndex].name,
      oldValue: originalStatus,
      newValue: status,
      timestamp: new Date().toISOString(),
      ip: req.ip,
      userAgent: req.headers['user-agent']
    };
    
    // 添加到操作日志数组
    if (!db.data.operationLogs) {
      db.data.operationLogs = [];
    }
    db.data.operationLogs.push(operationLog);
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: db.data.leads[leadIndex],
      message: '更新线索状态成功'
    });
  } catch (error) {
    console.error('更新线索状态失败:', error);
    res.status(500).json({
      success: false,
      message: '更新线索状态失败'
    });
  }
});

// 从线索添加客户信息
app.get('/api/v1/leads/:id/add-to-customers', requirePermission('leads'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const lead = db.data.leads.find(l => l.id === id);
    
    if (!lead) {
      return res.status(404).json({
        success: false,
        message: '线索不存在'
      });
    }
    
    // 检查是否已经存在相同电话或邮箱的客户
    const existingCustomer = db.data.customers.find(customer => 
      customer.phone === lead.phone || (lead.email && customer.email === lead.email)
    );
    
    if (existingCustomer) {
      return res.status(400).json({
        success: false,
        message: '该客户已存在'
      });
    }
    
    // 创建新客户
    const newCustomer = {
      id: getNextId('customer'),
      wechatAvatar: lead.wechatAvatar || '',
      wechatNickname: lead.wechatNickname || '',
      name: lead.name,
      phone: lead.phone,
      email: lead.email || '',
      customerType: '普通客户',
      permissions: {
        viewWorks: true,
        categories: []
      },
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // 添加到数据库
    db.data.customers.push(newCustomer);
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: newCustomer,
      message: '客户信息添加成功'
    });
  } catch (error) {
    console.error('从线索添加客户信息失败:', error);
    res.status(500).json({
      success: false,
      message: '客户信息添加失败'
    });
  }
});

// 根据OpenID获取用户权限
app.get('/api/v1/permissions/:openId', (req, res) => {
  try {
    const openId = req.params.openId;
    
    // 查找具有该OpenID的客户
    const customer = db.data.customers.find(c => c.wechatOpenId === openId);
    
    if (customer && customer.permissions) {
      res.json({
        success: true,
        data: customer.permissions,
        message: '获取用户权限成功'
      });
    } else {
      // 如果没有找到客户，返回默认权限
      res.json({
        success: true,
        data: {
          viewWorks: true,
          categories: []
        },
        message: '用户未找到，使用默认权限'
      });
    }
  } catch (error) {
    console.error('获取用户权限失败:', error);
    res.status(500).json({
      success: false,
      data: {
        viewWorks: true,
        categories: []
      },
      message: '获取用户权限失败，使用默认权限'
    });
  }
});

// 系统设置API端点

// 获取系统设置
app.get('/api/v1/settings', requirePermission('settings'), (req, res) => {
  try {
    // 从数据库获取系统设置
    const settings = db.data.settings;
    res.json({
      success: true,
      data: settings,
      message: '获取系统设置成功'
    });
  } catch (error) {
    console.error('获取系统设置失败:', error);
    res.status(500).json({
      success: false,
      message: '获取系统设置失败'
    });
  }
});

// 更新系统设置
app.put('/api/v1/settings', requirePermission('settings'), (req, res) => {
  try {
    // 更新系统设置
    db.data.settings = { ...db.data.settings, ...req.body };
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: db.data.settings,
      message: '更新系统设置成功'
    });
  } catch (error) {
    console.error('更新系统设置失败:', error);
    res.status(500).json({
      success: false,
      message: '更新系统设置失败',
      error: error.message
    });
  }
});

// 关于我们API端点

// 获取关于我们数据
app.get('/api/v1/about', (req, res) => {
  try {
    // 从数据库获取关于我们数据
    const aboutData = db.data.about;
    res.json({
      success: true,
      data: aboutData,
      message: '获取关于我们数据成功'
    });
  } catch (error) {
    console.error('获取关于我们数据失败:', error);
    res.status(500).json({
      success: false,
      message: '获取关于我们数据失败'
    });
  }
});

// 更新关于我们数据
app.put('/api/v1/about', requirePermission('brand'), (req, res) => {
  try {
    // 更新关于我们数据
    db.data.about = { ...db.data.about, ...req.body };
    
    // 保存数据库
    db.write();
    
    res.json({
      success: true,
      data: db.data.about,
      message: '更新关于我们数据成功'
    });
  } catch (error) {
    console.error('更新关于我们数据失败:', error);
    res.status(500).json({
      success: false,
      message: '更新关于我们数据失败',
      error: error.message
    });
  }
});

// 用户管理API端点

// 获取用户列表
app.get('/api/v1/users', requirePermission('users'), (req, res) => {
  try {
    // 从数据库获取所有用户
    const users = db.data.users;
    res.json({
      success: true,
      data: users,
      message: '获取用户列表成功'
    });
  } catch (error) {
    console.error('获取用户列表失败:', error);
    res.status(500).json({
      success: false,
      message: '获取用户列表失败'
    });
  }
});





// 获取当前登录用户信息
app.get('/api/v1/users/current', requireAuth, (req, res) => {
  try {
    if (req.session.user) {
      // 从数据库中获取完整的用户信息
      const user = db.data.users.find(u => u.username === req.session.user.username);
      if (user) {
        res.json({
          success: true,
          data: {
            id: user.id,
            username: user.username,
            role: user.role,
            permissions: user.permissions
          },
          message: '获取用户信息成功'
        });
      } else {
        res.status(404).json({
          success: false,
          message: '用户不存在'
        });
      }
    } else {
      res.status(401).json({
        success: false,
        message: '未登录'
      });
    }
  } catch (error) {
    console.error('获取用户信息失败:', error);
    res.status(500).json({
      success: false,
      message: '获取用户信息失败'
    });
  }
});



// 静态文件路由
app.use(express.static(path.join(__dirname, 'public')));

// 初始化数据库并启动服务器
async function startServer() {
  try {
    // 初始化数据库
    await initDatabase();
    console.log('数据库初始化成功');
    
    // 启动服务器
    app.listen(PORT, () => {
      console.log(`Admin web server is running on http://localhost:${PORT}`);
    });
  } catch (error) {
    console.error('服务器启动失败:', error);
    process.exit(1);
  }
}

// 日志管理API端点

// 获取用户日志
app.get('/api/v1/logs', requirePermission('users'), (req, res) => {
  try {
    const { userId } = req.query;
    
    let logs = [...db.data.logs];
    
    // 如果指定了用户ID，进行筛选
    if (userId) {
      logs = logs.filter(log => log.userId === parseInt(userId));
    }
    
    // 按创建时间倒序排序
    logs = logs.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    
    res.json({
      success: true,
      data: logs,
      message: '获取日志列表成功'
    });
  } catch (error) {
    console.error('获取日志列表失败:', error);
    res.status(500).json({
      success: false,
      message: '获取日志列表失败'
    });
  }
});

// 日志记录函数
function logOperation(req, actionType, actionContent) {
  try {
    if (req.session.user) {
      const user = db.data.users.find(u => u.username === req.session.user.username);
      if (user) {
        const newLog = {
          id: db.data.logs.length + 1,
          userId: user.id,
          username: user.username,
          actionType,
          actionContent,
          ipAddress: req.ip || 'unknown',
          createdAt: new Date().toISOString()
        };
        
        db.data.logs.push(newLog);
        db.write();
      }
    }
  } catch (error) {
    console.error('记录日志失败:', error);
  }
}

// 登录成功后记录日志
app.post('/login', async (req, res) => {
  const { username, password } = req.body;
  
  try {
    // 查找用户
    const user = db.data.users.find(u => u.username === username);
    
    if (user) {
      // 验证密码
      const match = await bcrypt.compare(password, user.password);
      if (match) {
        req.session.user = user;
        
        // 记录登录日志
        logOperation(req, 'login', '用户登录系统');
        
        res.json({ success: true, redirect: '/dashboard' });
      } else {
        res.json({ success: false, message: '用户名或密码错误' });
      }
    } else {
      res.json({ success: false, message: '用户名或密码错误' });
    }
  } catch (error) {
    console.error('登录验证失败:', error);
    res.status(500).json({ success: false, message: '登录验证失败' });
  }
});

// 编辑用户后记录日志
app.put('/api/v1/users/:id', requirePermission('users'), async (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const userIndex = db.data.users.findIndex(u => u.id === id);
    
    if (userIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '用户不存在'
      });
    }
    
    const { username, password, role, permissions } = req.body;
    
    // 验证必填字段
    if (!username) {
      return res.status(400).json({
        success: false,
        message: '用户名为必填字段'
      });
    }
    
    // 验证用户名是否已存在（排除当前用户）
    const existingUser = db.data.users.find(u => u.username === username && u.id !== id);
    if (existingUser) {
      return res.status(400).json({
        success: false,
        message: '用户名已存在'
      });
    }
    
    // 更新用户信息
    const updatedUser = {
      ...db.data.users[userIndex],
      username,
      role: role || db.data.users[userIndex].role,
      permissions: permissions || db.data.users[userIndex].permissions,
      updatedAt: new Date().toISOString()
    };
    
    // 如果提供了新密码，更新密码
    if (password) {
      const hashedPassword = await bcrypt.hash(password, saltRounds);
      updatedUser.password = hashedPassword;
    }
    
    // 更新数据库
    db.data.users[userIndex] = updatedUser;
    
    // 保存数据库
    db.write();
    
    // 记录操作日志
    logOperation(req, 'user_edit', `编辑用户: ${updatedUser.username}`);
    
    res.json({
      success: true,
      data: updatedUser,
      message: '编辑用户成功'
    });
  } catch (error) {
    console.error('编辑用户失败:', error);
    res.status(500).json({
      success: false,
      message: '编辑用户失败'
    });
  }
});

// 添加用户后记录日志
app.post('/api/v1/users', requirePermission('users'), async (req, res) => {
  try {
    const { username, password, role, permissions } = req.body;
    
    // 验证必填字段
    if (!username || !password) {
      return res.status(400).json({
        success: false,
        message: '用户名和密码为必填字段'
      });
    }
    
    // 验证用户名是否已存在
    const existingUser = db.data.users.find(u => u.username === username);
    if (existingUser) {
      return res.status(400).json({
        success: false,
        message: '用户名已存在'
      });
    }
    
    // 加密密码
    const hashedPassword = await bcrypt.hash(password, saltRounds);
    
    // 创建新用户
    const newUser = {
      id: db.data.users.length + 1,
      username,
      password: hashedPassword,
      role: role || 'admin',
      permissions: permissions || {
        dashboard: true,
        works: true,
        categories: true,
        leads: true,
        customers: true,
        brand: true,
        stats: true,
        settings: true,
        users: true
      },
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // 添加到数据库
    db.data.users.push(newUser);
    
    // 保存数据库
    db.write();
    
    // 记录操作日志
    logOperation(req, 'user_add', `添加用户: ${newUser.username}`);
    
    res.status(201).json({
      success: true,
      data: newUser,
      message: '添加用户成功'
    });
  } catch (error) {
    console.error('添加用户失败:', error);
    res.status(500).json({
      success: false,
      message: '添加用户失败'
    });
  }
});

// 删除用户后记录日志
app.delete('/api/v1/users/:id', requirePermission('users'), (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const userIndex = db.data.users.findIndex(u => u.id === id);
    
    if (userIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '用户不存在'
      });
    }
    
    const username = db.data.users[userIndex].username;
    
    // 不能删除最后一个管理员用户
    const remainingAdmins = db.data.users.filter(u => u.id !== id && u.role === 'admin');
    if (db.data.users[userIndex].role === 'admin' && remainingAdmins.length === 0) {
      return res.status(400).json({
        success: false,
        message: '不能删除最后一个管理员用户'
      });
    }
    
    // 删除用户
    db.data.users.splice(userIndex, 1);
    
    // 保存数据库
    db.write();
    
    // 记录操作日志
    logOperation(req, 'user_delete', `删除用户: ${username}`);
    
    res.json({
      success: true,
      message: '删除用户成功'
    });
  } catch (error) {
    console.error('删除用户失败:', error);
    res.status(500).json({
      success: false,
      message: '删除用户失败'
    });
  }
});

// 初始化数据库并启动服务器
async function startServer() {
  try {
    // 初始化数据库
    await initDatabase();
    console.log('数据库初始化成功');
    
    // 启动服务器
    app.listen(PORT, () => {
      console.log(`Admin web server is running on http://localhost:${PORT}`);
    });
  } catch (error) {
    console.error('服务器启动失败:', error);
    process.exit(1);
  }
}

// 执行服务器启动
startServer();
