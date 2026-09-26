require 'json'

package = JSON.parse(File.read(File.join(__dir__, '..', 'package.json')))

Pod::Spec.new do |s|
  s.name           = 'ExpoRoomPlan'
  s.version        = package['version']
  s.summary        = package['description']
  s.description    = package['description']
  s.license        = package['license']
  s.author         = package['author']
  s.homepage       = package['homepage']
  s.platforms      = { :ios => '15.1' }
  s.swift_version  = '5.9'
  s.source         = { :git => '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  # RoomPlan itself is iOS 16+ (`ExpoRoomPlanView` is `@available(iOS 16.0, *)`); the pod's
  # own deployment target stays at the app's floor so devices below iOS 16 still install
  # the app and simply never see the LiDAR path (see capabilities.ts / isRoomPlanSupported).
  s.source_files = '**/*.{h,m,swift}'
end
