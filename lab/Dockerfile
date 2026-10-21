FROM jenkins/jenkins:lts-jdk21

COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

# Sin asistente de instalación: toda la configuración llega por JCasC (/casc).
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false -Dhudson.model.UsageStatistics.disabled=true"
ENV CASC_JENKINS_CONFIG=/casc/common.yaml
COPY casc /casc
