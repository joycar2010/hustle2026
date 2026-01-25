const mongoose = require('mongoose');

const WorkSchema = new mongoose.Schema({
  title: {
    type: String,
    required: true,
    trim: true
  },
  type: {
    type: String,
    required: true,
    trim: true
  },
  area: {
    type: Number,
    required: true
  },
  location: {
    type: String,
    required: true,
    trim: true
  },
  coverImage: {
    type: String,
    required: true,
    trim: true
  },
  images: {
    type: [String],
    required: true
  },
  description: {
    type: String,
    trim: true
  },
  views: {
    type: Number,
    default: 0
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
WorkSchema.index({ type: 1 });
WorkSchema.index({ location: 1 });
WorkSchema.index({ createdAt: -1 });

module.exports = mongoose.model('Work', WorkSchema);
