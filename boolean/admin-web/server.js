const express = require('express');
const session = require('express-session');
const bodyParser = require('body-parser');
const path = require('path');
const fs = require('fs');

// 导入lowdb数据库
const { db, initDatabase, getNextId } = require('./db');
const bcrypt = require('bcrypt');

// 创建数据目录
const dataDir = path.join(__dirname, 'data');
if (!fs.existsSync(dataDir)) {
  fs.mkdirSync(dataDir);
}

const app = express();
const PORT = process.env.PORT || 3000;

// 中间件配置
app.use(bodyParser.urlencoded({ extended: true, limit: '10mb' }));
app.use(bodyParser.json({ limit: '10mb' }));
app.use(express.static(path.join(__dirname, 'public')));

// 跨域配置
app.use((req, res, next) => {
  // 允许所有来源访问
  res.setHeader('Access-Control-Allow-Origin', '*');
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

// 根路径路由 - 重定向到登录页面
app.get('/', (req, res) => {
  if (req.session.user) {
    res.redirect('/dashboard');
  } else {
    res.redirect('/login');
  }
});

// 登录页面路由
app.get('/login', (req, res) => {
  if (req.session.user) {
    res.redirect('/dashboard');
  } else {
    res.sendFile(path.join(__dirname, 'public', 'login.html'));
  }
});

// 登录验证路由
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

// 仪表盘路由
app.get('/dashboard', (req, res) => {
  if (req.session.user) {
    res.sendFile(path.join(__dirname, 'public', 'dashboard.html'));
  } else {
    res.redirect('/login');
  }
});

// 作品管理页面路由
app.get('/works', (req, res) => {
  if (req.session.user) {
    res.sendFile(path.join(__dirname, 'public', 'works.html'));
  } else {
    res.redirect('/login');
  }
});

// 分类管理页面路由
app.get('/categories', (req, res) => {
  if (req.session.user) {
    res.sendFile(path.join(__dirname, 'public', 'categories.html'));
  } else {
    res.redirect('/login');
  }
});

// 线索管理页面路由
app.get('/leads', (req, res) => {
  if (req.session.user) {
    res.sendFile(path.join(__dirname, 'public', 'leads.html'));
  } else {
    res.redirect('/login');
  }
});

// 数据统计页面路由
app.get('/stats', (req, res) => {
  if (req.session.user) {
    res.sendFile(path.join(__dirname, 'public', 'stats.html'));
  } else {
    res.redirect('/login');
  }
});

// 系统设置页面路由
app.get('/settings', (req, res) => {
  if (req.session.user) {
    res.sendFile(path.join(__dirname, 'public', 'settings.html'));
  } else {
    res.redirect('/login');
  }
});

// 关于我们页面路由
app.get('/about', (req, res) => {
  if (req.session.user) {
    res.sendFile(path.join(__dirname, 'public', 'settings.html'));
  } else {
    res.redirect('/login');
  }
});

// 获取统计数据的API端点
app.get('/api/v1/stats', requireAuth, (req, res) => {
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
app.get('/api/v1/stats/detailed', requireAuth, (req, res) => {
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
    // 从数据库获取所有作品并按创建时间倒序排序
    const works = [...db.data.works].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    res.json({
      success: true,
      data: works,
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

// 获取单个作品详情
app.get('/api/v1/works/:id', (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const work = db.data.works.find(w => w.id === id);
    
    if (work) {
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
app.post('/api/v1/works', requireAuth, async (req, res) => {
  try {
    const { title, type, area, location, coverImage, images, description } = req.body;
    
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
      views: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // 添加到数据库
    db.data.works.push(newWork);
    
    // 更新分类的作品数量
    category.worksCount++;
    category.updatedAt = new Date().toISOString();
    
    // 保存数据库
    await db.write();
    
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
app.put('/api/v1/works/:id', requireAuth, async (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const workIndex = db.data.works.findIndex(w => w.id === id);
    
    if (workIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '作品不存在'
      });
    }
    
    const { title, type, area, location, coverImage, images, description } = req.body;
    
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
    await db.write();
    
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
app.delete('/api/v1/works/:id', requireAuth, async (req, res) => {
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
    await db.write();
    
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
app.get('/api/v1/categories/:id', requireAuth, (req, res) => {
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
app.post('/api/v1/categories', requireAuth, (req, res) => {
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
app.put('/api/v1/categories/:id', requireAuth, (req, res) => {
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
app.delete('/api/v1/categories/:id', requireAuth, (req, res) => {
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

// 线索管理API端点

// 获取线索列表
app.get('/api/v1/leads', requireAuth, (req, res) => {
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
app.get('/api/v1/leads/:id', requireAuth, (req, res) => {
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
app.post('/api/v1/leads', requireAuth, (req, res) => {
  try {
    const { name, phone, email, projectType, budget, status, description } = req.body;
    
    // 验证必填字段
    if (!name || !phone || !projectType || !status) {
      return res.status(400).json({
        success: false,
        message: '客户名称、联系电话、项目类型和状态为必填字段'
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
app.put('/api/v1/leads/:id', requireAuth, (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const leadIndex = db.data.leads.findIndex(l => l.id === id);
    
    if (leadIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '线索不存在'
      });
    }
    
    const { name, phone, email, projectType, budget, status, description } = req.body;
    
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
app.delete('/api/v1/leads/:id', requireAuth, (req, res) => {
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

// 系统设置API端点

// 获取系统设置
app.get('/api/v1/settings', requireAuth, (req, res) => {
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
app.put('/api/v1/settings', requireAuth, (req, res) => {
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
app.get('/api/v1/about', requireAuth, (req, res) => {
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
app.put('/api/v1/about', requireAuth, (req, res) => {
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
app.get('/api/v1/users', requireAuth, (req, res) => {
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

// 添加用户
app.post('/api/v1/users', requireAuth, async (req, res) => {
  try {
    const { username, password, role } = req.body;
    
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
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    
    // 添加到数据库
    db.data.users.push(newUser);
    
    // 保存数据库
    db.write();
    
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

// 编辑用户
app.put('/api/v1/users/:id', requireAuth, async (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const userIndex = db.data.users.findIndex(u => u.id === id);
    
    if (userIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '用户不存在'
      });
    }
    
    const { username, password, role } = req.body;
    
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

// 删除用户
app.delete('/api/v1/users/:id', requireAuth, (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const userIndex = db.data.users.findIndex(u => u.id === id);
    
    if (userIndex === -1) {
      return res.status(404).json({
        success: false,
        message: '用户不存在'
      });
    }
    
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
