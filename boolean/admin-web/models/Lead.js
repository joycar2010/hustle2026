const mongoose = require('mongoose');

const LeadSchema = new mongoose.Schema({
  name: {
    type: String,
    required: true,
    trim: true
  },
  phone: {
    type: String,
    required: true,
    trim: true
  },
  email: {
    type: String,
    trim: true
  },
  projectType: {
    type: String,
    required: true,
    trim: true
  },
  budget: {
    type: String,
    trim: true
  },
  status: {
    type: String,
    required: true,
    enum: ['new', 'processing', 'completed', 'canceled'],
    default: 'new'
  },
  description: {
    type: String,
    trim: true
  },
  createdAt: {
    type: Date,
    default: Date.now
  },
  updatedAt: {
    type: Date,
    default: Date.now
  }
});

// 添加索引以提高查询性能
LeadSchema.index({ status: 1 });
LeadSchema.index({ projectType: 1 });
LeadSchema.index({ createdAt: -1 });

module.exports = mongoose.model('Lead', LeadSchema);
